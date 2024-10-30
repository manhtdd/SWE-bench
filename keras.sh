#!/bin/bash

./swebench/collect/make_repo/make_repo.sh keras-team/keras $1
cd ./swebench/collect
mkdir output
./run_get_tasks_pipeline.sh 'keras-team/keras' 'output' 'output'