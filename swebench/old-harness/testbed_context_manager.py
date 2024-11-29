import logging
import os
import subprocess
from typing import List

logging.basicConfig(
    force=True,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger_testbed = logging.getLogger("testbed_context_manager")

from constants import (
    MAP_REPO_TO_INSTALL,
    MAP_REPO_TO_TEST_FRAMEWORK,
    MAP_VERSION_TO_INSTALL
)
from tempfile import TemporaryDirectory
from utils import (
    clone_repo,
    get_conda_env_names,
    get_environment_yml,
    get_requirements,
    get_test_directives,
)


class TestbedContextManager:
    def __init__(
        self,
        task_instances: List,
        log_dir: str,
        path_conda: str = None,
        testbed: str = None,
        verbose: bool = False,
        timeout: int = None,
        temp_dir: str = None,
    ):
        """
        Initialize testbed context. Creates temporary directories and groups task instances
        by repo/version.

        Args:
            task_instances (list): List of task instances
            log_dir (str): Path to log directory
            path_conda (str): Path to conda installation
            testbed (str): Path to testbed directory
            verbose (bool): Whether to show logs
            timeout (int): Timeout for actions
            temp_dir (str): Path to temporary directory
        """
        logger_testbed.propagate = verbose
        self.verbose = verbose
        self.log_dir = log_dir
        self.timeout = timeout
        # self.subprocess_args = {"check": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        self.subprocess_args = {"shell": True, "check": True, "executable": "/bin/bash"}

        # Create log, temp directories if they don't exist
        if not os.path.exists(self.log_dir):
            logger_testbed.info(f"[Testbed] Creating log directory {self.log_dir}")
            os.makedirs(self.log_dir, exist_ok=True)
        if temp_dir is not None and not os.path.exists(temp_dir):
            logger_testbed.info(f"[Testbed] Creating temp directory {temp_dir}")
            os.makedirs(temp_dir, exist_ok=True)

        # Set up conda path, create in temp directory if None
        if path_conda is not None:
            self.temp_dir_conda = None
            self.path_conda = path_conda
        else:
            self.temp_dir_conda = TemporaryDirectory(dir=temp_dir)
            self.path_conda = self.temp_dir_conda.name
        logger_testbed.info(f"[Testbed] Using conda path {self.path_conda}")

        # Set up testbed path, create in temp directory if None
        if testbed is not None:
            self.temp_dir_work = None
            self.testbed = testbed
        else:
            self.temp_dir_work = TemporaryDirectory(dir=temp_dir)
            self.testbed = self.temp_dir_work.name
        logger_testbed.info(f"[Testbed] Using working directory {self.testbed} for testbed")

        # Sort task instances by created_at
        self.task_instances = sorted(task_instances, key=lambda x: x["created_at"], reverse=True)

        # Group repos by repo, then version
        self.task_instances_grouped = {}
        for instance in self.task_instances:
            # Create test command from framework + directives
            test_type = MAP_REPO_TO_TEST_FRAMEWORK[instance["repo"]]
            test_directives = get_test_directives(instance)
            instance["test_cmd"] = f"{test_type} {' '.join(test_directives)}"

            # Group task instances by repo, version
            repo = instance["repo"]
            version = instance["version"] if "version" in instance else None
            if repo not in self.task_instances_grouped:
                self.task_instances_grouped[repo] = {}
            if version not in self.task_instances_grouped[repo]:
                self.task_instances_grouped[repo][version] = []
            self.task_instances_grouped[repo][version].append(instance)

        # Log grouped task instances to be run
        self.setup_refs = {}
        for repo, map_version_to_instances in self.task_instances_grouped.items():
            logger_testbed.info(f"[Testbed] Repo {repo}: {len(map_version_to_instances)} versions")

            # Determine instances to use for environment installation
            self.setup_refs[repo] = {}
            for version, instances in map_version_to_instances.items():
                logger_testbed.info(f"[Testbed] \tVersion {version}: {len(instances)} instances")
                self.setup_refs[repo][version] = instances[0]

        # Remove None versions, versions not in MAP_VERSION_TO_INSTALL
        self._custom_restraints()
        
    def _run_command(self, command:str, cwd:str = '.'):
        subprocess.run(command, cwd=cwd, **self.subprocess_args)

    def __enter__(self):
        """
        Set up testbed (conda environments, git repositories)
        """
        # If path_conda not provided, create temporary miniconda3 installation
        if self.temp_dir_conda is not None:
            # Set up the paths for Miniconda
            self.path_conda = os.path.join(self.path_conda, "miniconda3")
            os.mkdir(self.path_conda)
            miniconda_sh = os.path.join(self.path_conda, "miniconda.sh")
            logger_testbed.info(f"No conda path provided, creating temporary install in {self.path_conda}...")

            # Download Miniconda installer
            download_cmd = f"wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O {miniconda_sh}"
            self._run_command(download_cmd)

            # Install Miniconda
            install_cmd = f"bash {miniconda_sh} -b -u -p {self.path_conda}"
            self._run_command(install_cmd)

            # Clean up the installer
            os.remove(miniconda_sh)
        logger_testbed.info(f"[Testbed] Using conda path {self.path_conda}")

        # Set up conda executables, get existing environments
        self.path_conda = os.path.abspath(self.path_conda)
        path_activate = os.path.join(self.path_conda, "bin", "activate")
        exec_type = "mamba" if "mamba" in self.path_conda else "conda"
        exec_cmd = os.path.join(self.path_conda, "bin", exec_type)
        env_list = get_conda_env_names(exec_cmd)

        # Set up testbed (environment, github repo) for each repo
        for repo, version_to_setup_ref in self.setup_refs.items():
            repo_prefix = repo.replace("/", "__")

            # Run any repo-level installation commands if provided
            if repo in MAP_REPO_TO_INSTALL:
                install_cmd = MAP_REPO_TO_INSTALL[repo]
                logger_testbed.info(f"[Testbed] Running custom install command for {repo}: {install_cmd}")
                self._run_command(install_cmd)

            # Create conda environment per version of the repo
            for version, install in MAP_VERSION_TO_INSTALL[repo].items():
                # Skip if none of the task instances are for this version
                if version not in version_to_setup_ref:
                    continue

                # Name for both environment and github repo
                env_name = f"{repo_prefix}__{version}"
                logger_testbed.info(f"[Testbed] Setting up testbed for {env_name}")

                # Clone github per repo/version
                repo_path = os.path.join(self.testbed, env_name)
                if not os.path.exists(repo_path):
                    clone_repo(repo, repo_path)
                    logger_testbed.info(f"[Testbed] Cloned {repo} to {repo_path}")
                else:
                    logger_testbed.info(
                        f"[Testbed] Repo for {repo_prefix} version {version} exists: {repo_path}; skipping"
                    )

                # Skip if conda environment already exists
                if env_name in env_list:
                    logger_testbed.info(
                        f"[Testbed] Environment {env_name} already exists; skipping"
                    )
                    continue

                # Get setup reference instance
                setup_ref_instance = version_to_setup_ref[version]

                # Create conda environment according to install instructinos
                pkgs = install["packages"] if "packages" in install else ""
                if pkgs == "requirements.txt":
                    # Create environment
                    cmd = f"{exec_cmd} create -n {env_name} python={install['python']} -y"
                    logger_testbed.info(f"[Testbed] Creating environment {env_name}; Command: {cmd}")
                    self._run_command(cmd)

                    # Install dependencies
                    path_to_reqs = get_requirements(setup_ref_instance, self.testbed)
                    cmd = f"source {path_activate} {env_name} && pip install -r {path_to_reqs}"
                    logger_testbed.info(f"[Testbed] Installing dependencies for {env_name}; Command: {cmd}")
                    self._run_command(cmd)
                    os.remove(path_to_reqs)
                elif pkgs == "environment.yml":
                    # Create environment from yml
                    path_to_reqs = get_environment_yml(setup_ref_instance, env_name, self.testbed)
                    if "no_use_env" in install and install["no_use_env"]:
                        # `conda create` based installation
                        cmd = f"{exec_cmd} create -c conda-forge -n {env_name} python={install['python']} -y"
                        logger_testbed.info(f"[Testbed] Creating environment {env_name}; Command: {cmd}")
                        self._run_command(cmd)

                        # Install dependencies
                        cmd = f"{exec_cmd} env update -f {path_to_reqs}"
                        logger_testbed.info(f"[Testbed] Installing dependencies for {env_name}; Command: {cmd}")
                        self._run_command(cmd)
                    else:
                        # `conda env create` based installation
                        cmd = f"{exec_cmd} env create --file {path_to_reqs}"
                        logger_testbed.info(f"[Testbed] Creating environment {env_name}; Command: {cmd}")
                        self._run_command(cmd)

                    # Remove environment.yml
                    os.remove(path_to_reqs)
                else:
                    # Create environment + install dependencies
                    cmd = f"{exec_cmd} create -n {env_name} python={install['python']} {pkgs} -y"
                    logger_testbed.info(f"[Testbed] Creating environment {env_name}; Command: {cmd}")
                    self._run_command(cmd)

                # Install additional packages if specified
                if "pip_packages" in install:
                    cmd = f"source {path_activate} {env_name} && pip install {install['pip_packages']}"
                    logger_testbed.info(f"[Testbed] Installing pip packages for {env_name}; Command: {cmd}")
                    self._run_command(cmd)

        return self

    def get_distributed_tasks(self) -> List:
        """
        Create task group (instances + keywords) for each repo/version

        Returns:
            list: List of task groups, each group containing task instances
                from the same repo with the same version
        """
        distributed_tasks = []
        for repo, map_version_to_instances in self.task_instances_grouped.items():
            repo_prefix = repo.replace("/", "__")
            for version, instances in map_version_to_instances.items():
                env_name = f"{repo_prefix}__{version}"
                task_set = {
                    "conda_path": self.path_conda,
                    "log_dir": self.log_dir,
                    "task_instances": instances,
                    "testbed": os.path.join(self.testbed, env_name),
                    "timeout": self.timeout,
                    "venv": env_name,
                    "version": version,
                    "verbose": self.verbose,
                }
                distributed_tasks.append(task_set)
        return distributed_tasks

    def _custom_restraints(self):
        """
        Custom restraints per repo
        """
        for repo, group in self.task_instances_grouped.items():
            if None in group:
                logger_testbed.info(f"[Testbed] Removed None version from repo {repo}")
                del group[None]
            versions = list(group.keys())
            for version in versions:
                if version not in MAP_VERSION_TO_INSTALL[repo]:
                    logger_testbed.info(f"[Testbed] Removed {version} version from repo {repo} (Install instructions not given)")
                    del group[version]

    def __exit__(self, exc_type, exc_value, exc_traceback):
        # if self.temp_dir_work is not None:
        #     self.temp_dir_work.cleanup()
        # if self.temp_dir_conda is not None:
        #     self.temp_dir_conda.cleanup()
        pass