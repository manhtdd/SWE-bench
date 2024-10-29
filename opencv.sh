#!/bin/bash

./swebench/collect/make_repo/make_repo.sh opencv/opencv $1
cd ./swebench/collect
mkdir output
./run_get_tasks_pipeline.sh 'opencv/opencv' 'output' 'output'