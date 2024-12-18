#!/usr/bin/env bash

# Mirror repository to https://github.com/swe-bench
# Usage: make_repo.sh {gh organization}/{gh repository}

# Abort on error
TOKEN=$1
REPO_TARGET=$2
DESIRED_BRANCH=$3

# Check if the target repository exists
echo "gh repo view $REPO_TARGET > /dev/null || exit 1"
gh repo view "$REPO_TARGET" > /dev/null || exit 1

# Set the organization and repository names
ORG_NAME="manhtdd"
NEW_REPO_NAME="$(basename "$REPO_TARGET")__$(basename "$REPO_TARGET")"

# Check if the new repository already exists
echo "gh repo view $ORG_NAME/$NEW_REPO_NAME > /dev/null 2>&1"
gh repo view "$ORG_NAME/$NEW_REPO_NAME" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "The repository $ORG_NAME/$NEW_REPO_NAME already exists."
    exit 1
fi

# Create mirror repository
echo "gh repo create $ORG_NAME/$NEW_REPO_NAME --private"
gh repo create "$ORG_NAME/$NEW_REPO_NAME" --private

# Check if the repository creation was successful
if [ $? -eq 0 ]; then
    echo "** Repository created successfully at $ORG_NAME/$NEW_REPO_NAME."
else
    echo "Failed to create the repository."
    exit 1
fi

# Clone the target repository
echo "** Cloning $REPO_TARGET..."
TARGET_REPO_DIR="${REPO_TARGET##*/}.git"

# Check if the local repository directory already exists
if [ -d "$TARGET_REPO_DIR" ]; then
    echo "The local repository directory $TARGET_REPO_DIR already exists."
    exit 1
fi

# Clone the repository using HTTPS
git clone --bare https://github.com/$REPO_TARGET.git "$TARGET_REPO_DIR"

# Push files to the mirror repository
echo "** Performing mirror push of files to $ORG_NAME/$NEW_REPO_NAME..."
cd "$TARGET_REPO_DIR"; git push --mirror https://manhtdd:$TOKEN@github.com/$ORG_NAME/$NEW_REPO_NAME.git

# Remove the target repository
cd ..; rm -rf "$TARGET_REPO_DIR"

# Clone the mirror repository
git clone https://manhtdd:$TOKEN@github.com/$ORG_NAME/$NEW_REPO_NAME.git

# Delete .github/workflows if it exists
if [ -d "$NEW_REPO_NAME/.github/workflows" ]; then
    # Remove the directory
    rm -rf "$NEW_REPO_NAME/.github/workflows"

    # Commit and push the changes
    cd "$NEW_REPO_NAME";
    git add -A;
    git commit -m "Removed .github/workflows";
    git push origin $DESIRED_BRANCH;  # Change 'main' to your desired branch
    cd ..;
else
    echo "$REPO_NAME/.github/workflows does not exist. No action required."
fi

rm -rf "$NEW_REPO_NAME"
