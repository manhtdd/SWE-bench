#!/bin/bash

./swebench/collect/make_repo/make_repo.sh opencv/opencv $1
cd ./swebench/collect
./run_get_tasks_pipeline.sh 'opencv/opencv' 'opencv-prs.jsonl' 'opencv-task-instances.jsonl'