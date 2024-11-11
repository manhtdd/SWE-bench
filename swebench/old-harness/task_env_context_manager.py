import logging
import os
import subprocess
from constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    INSTALL_FAIL,
    INSTALL_PASS,
    INSTALL_TIMEOUT,
    KEY_INSTANCE_ID,
    KEY_MODEL,
    MAP_VERSION_TO_INSTALL,
    RESET_FAILED,
    TESTS_FAILED,
    TESTS_PASSED,
    TESTS_TIMEOUT,
    TESTS_ERROR,
)
from typing import Dict

logger_taskenv = logging.getLogger("taskenv_context_manager")

class TaskEnvContextManager:
    def __init__(
        self,
        instance: Dict,
        testbed: str,
        venv: str,
        log_dir: str,
        conda_path: str,
        verbose: bool = False,
        timeout: int = None,
        is_eval: bool = False,
    ):
        """
        Sets up execution context for a single task instance

        Args:
            instance (dict): Task instance
            testbed (str): Path to testbed directory
            venv (str): Name of conda environment (should exist in conda_path)
            log_dir (str): Path to log directory
            conda_path (str): Path to conda installation
            verbose (bool): Whether to show logs
            timeout (int): Timeout for actions
            is_eval (bool): Whether this is for evaluating a model on SWE Bench
                (Mainly for logging purposes)
        """
        logger_taskenv.propagate = verbose
        self.instance = instance
        self.testbed = testbed
        self.testbed_name = testbed.split("/")[-1]
        self.venv = venv
        self.conda_path = conda_path
        self.log_file = os.path.join(log_dir, f"{instance[KEY_INSTANCE_ID]}.log")
        self.is_eval = is_eval
        if is_eval:
            self.log_file = os.path.join(log_dir, f"{instance[KEY_INSTANCE_ID]}.{instance[KEY_MODEL]}.eval.log")
        self.cmd_activate = (f"source {os.path.join(self.conda_path, 'bin', 'activate')} {self.venv}")
        self.timeout = timeout
        self.cwd = os.getcwd()
        # self.subprocess_args = {"check": True, "shell": True, "executable": "/bin/bash", "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        self.subprocess_args = {"check": True, "shell": True, "executable": "/bin/bash"}
        
    def _run_command(self, command:str, subprocess_args:Dict=None, cwd:str="."):
        subprocess_args = subprocess_args if subprocess_args else self.subprocess_args
        return subprocess.run(command, cwd=cwd, **subprocess_args)

    def __enter__(self):
        """
        Enter task environment, set up log file
        """
        # os.chdir(self.testbed)
        with open(self.log_file, "w") as f:
            f.write(f"Task Metadata:\n\t- Instance ID: {self.instance[KEY_INSTANCE_ID]}\n\t- Testbed: {self.testbed}\n\t- Virtual Env.: {self.venv}\n")
            if self.is_eval:
                f.write(f"\t- Evaluation Model: {self.instance[KEY_MODEL]}\n")
        return self

    def reset_task_env(self, instance: Dict):
        """
        Reset task environment + testbed and checkout base commit of given task instance

        Args:
            instance (dict): Task instance
        Returns:
            bool: True if reset successful, False otherwise
        """
        try:
            # Remove all paths in .gitignore
            if os.path.exists(".gitignore"):
                with open(".gitignore", "r") as f:
                    for line in f.readlines():
                        if line.startswith("#") or line.strip() == "":
                            continue
                        self._run_command(f"rm -rf {line}")

            # Reset git repo + checkout base commit
            self._run_command("git restore .", cwd=self.testbed)
            self._run_command("git reset HEAD .", cwd=self.testbed)
            self._run_command("git clean -fdx", cwd=self.testbed)
            self._run_command(f"git -c advice.detachedHead=false checkout {instance['base_commit']}", cwd=self.testbed)
            logger_taskenv.info(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Reset task environment to {instance['base_commit']}")
            return True
        except Exception as e:
            err_msg = (f"{RESET_FAILED}; Failed to reset task environment to {instance['base_commit']}: {e}")
            logger_taskenv.error(f"[{self.testbed_name}] {err_msg}")
            with open(self.log_file, "a") as f:
                f.write(err_msg)
            return False

    def run_install_task(self, instance: Dict) -> bool:
        """
        Run installation for task instance

        Args:
            instance (dict): Task instance
        Returns:
            bool: True if installation successful, False otherwise
        """
        # Get installation instructions by repo/version
        specifications = MAP_VERSION_TO_INSTALL[instance["repo"]][instance["version"]]

        # Run pre-install set up if provided
        if "pre_install" in specifications:
            for pre_install in specifications["pre_install"]:
                cmd_pre_install = f"{self.cmd_activate}; {pre_install}"
                logger_taskenv.info(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Running pre-install setup command: {cmd_pre_install}")
                subprocess_args = {"shell":True, "executable": "/bin/bash", "text":True, "stdout":subprocess.PIPE, "stderr":subprocess.PIPE, "timeout":self.timeout}
                out_pre_install = self._run_command(cmd_pre_install, subprocess_args, cwd=self.testbed)
                with open(self.log_file, "a") as f:
                    f.write(f"Pre-installation Command: {cmd_pre_install}\n")
                    f.write(f"Std. Output: {out_pre_install.stdout}\n")
                    f.write(f"Std. Error: {out_pre_install.stderr}\n")
                if out_pre_install.returncode != 0:
                    logger_taskenv.error(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Pre-install setup failed")
                    with open(self.log_file, "a") as f:
                        f.write(f"\n{INSTALL_FAIL}\n")
                    return False

        cmd_install = f"{self.cmd_activate}; {specifications['install']}"
        logger_taskenv.info(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Installing with command: {cmd_install}")
        try:
            # Run installation command
            subprocess_args = {"shell":True, "executable": "/bin/bash", "text":True, "stdout":subprocess.PIPE, "stderr":subprocess.PIPE, "timeout":self.timeout}
            out_install = self._run_command(cmd_install, subprocess_args=subprocess_args, cwd=self.testbed)
            # Write installation logs to log file
            with open(self.log_file, "a") as f:
                f.write(f"Installation Command: {cmd_install}\n")
                f.write(f"Std. Output: {out_install.stdout}\n")
                f.write(f"Std. Error: {out_install.stderr}\n")

            if out_install.returncode != 0:
                # Installation failed
                logger_taskenv.error(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Installation failed")
                with open(self.log_file, "a") as f:
                    f.write(f"\n{INSTALL_FAIL}\n")
                return False

            # Installation successful
            logger_taskenv.info(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Installation successful")
            with open(self.log_file, "a") as f:
                f.write(f"\n{INSTALL_PASS}\n")
            return True
        except subprocess.TimeoutExpired:
            # Installation timed out
            logger_taskenv.error(f"[{self.testbed_name}] [{self.instance[KEY_INSTANCE_ID]}] Installation timed out")
            with open(self.log_file, "a") as f:
                f.write(f"\n{INSTALL_TIMEOUT}\n")
            return False

    def apply_patch(
        self, patch: str, patch_type: str = "", revert: bool = False
    ) -> bool:
        """
        Apply patch to task environment

        Args:
            patch (str): Plaintext of patch to apply
            patch_type (str): Type of patch (e.g. "eval", "test")
        Returns:
            bool: True if patch applied successfully, False otherwise
        """
        # If patch is `None`, indicate in log and skip
        if patch is None:
            logger_taskenv.error(f"[{self.testbed_name}] [{self.instance[KEY_INSTANCE_ID]}] Patch is `None` ({patch_type})")
            with open(self.log_file, "a") as f:
                f.write(f"{APPLY_PATCH_FAIL}; Prediction patch is `None`")
            return False

        # Write patch to temporary patch file in parent directory
        patch_path = os.path.join(
            os.path.dirname(self.testbed.rstrip("/")),
            f"temp_{self.instance[KEY_INSTANCE_ID]}_{patch_type}.patch",
        )
        with open(patch_path, "w") as f:
            f.write(patch)

        # Apply patch to testbed directory
        apply_cmd = f"git apply -v -R {patch_path}" if revert else f"git apply -v {patch_path}"
        subprocess_args = {"shell":True, "executable": "/bin/bash", "text":True, "stdout":subprocess.PIPE, "stderr":subprocess.PIPE, "timeout":self.timeout}
        out_patch = self._run_command(apply_cmd, subprocess_args, cwd=self.testbed)
        os.remove(patch_path)

        log_cmd = "Revert" if revert else "Apply"
        if out_patch.returncode != 0:
            # Patch apply failed
            logger_taskenv.error(f"[{self.testbed_name}] [{self.instance[KEY_INSTANCE_ID]}] {log_cmd} patch failed ({patch_type})")
            with open(self.log_file, "a") as f:
                f.write(f"{APPLY_PATCH_FAIL}; ({patch_type})\nOutput:\n")
                f.write(out_patch.stdout)
                f.write(out_patch.stderr)
            return False

        # Patch apply succeeded
        logger_taskenv.info(f"[{self.testbed_name}] [{self.instance[KEY_INSTANCE_ID]}] {log_cmd} patch successful ({patch_type})")
        with open(self.log_file, "a") as f:
            f.write(f"{APPLY_PATCH_PASS} ({patch_type})\n")
        return True

    def run_tests_task(self, instance: Dict):
        """
        Run tests for task instance

        Args:
            instance (dict): Task instance
        Returns:
            bool: True if test script ran successfully, False otherwise
        """
        try:
            # Run test command for task instance
            test_cmd = f"{self.cmd_activate}; {instance['test_cmd']}"
            with open(self.log_file, "a") as f:
                f.write(f"Test Script: {test_cmd};\n")
            subprocess_args = {"shell":True, "executable": "/bin/bash", "capture_output":True, "timeout":self.timeout}
            out_test = self._run_command(test_cmd, subprocess_args, cwd=self.testbed)

            # Write test results to log file
            with open(self.log_file, "a") as f:
                f.write(f"Output:\n")
                f.write(out_test.stdout.decode("utf-8"))
                f.write(out_test.stderr.decode("utf-8"))
                if out_test.returncode != 0:
                    f.write(f"\n{TESTS_FAILED}\n")
                else:
                    f.write(f"\n{TESTS_PASSED}\n")

            logger_taskenv.info(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Test script run successful")
            return True
        except subprocess.TimeoutExpired:
            # Test command run timed out
            logger_taskenv.error(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Test script run time out {self.timeout}")
            with open(self.log_file, "a") as f:
                f.write(f"{TESTS_TIMEOUT} after {self.timeout} seconds\n")
            return False
        except Exception as e:
            # Test command run failed
            logger_taskenv.error(f"[{self.testbed_name}] [{instance[KEY_INSTANCE_ID]}] Test script run failed")
            with open(self.log_file, "a") as f:
                f.write(f"{TESTS_ERROR}: {e}")
            return False

    def __exit__(self, exc_type, exc_value, exc_traceback):
        pass
