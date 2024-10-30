#!/bin/bash

./swebench/collect/make_repo/make_repo.sh $1 $2
cd ./swebench/collect
mkdir output
./run_get_tasks_pipeline.sh $1 'output' 'output'