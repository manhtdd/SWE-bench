#!/bin/bash

./swebench/collect/make_repo/make_repo.sh $1 keras-team/keras master
cd ./swebench/collect
mkdir output
./run_get_tasks_pipeline.sh 'keras-team/keras' 'output' 'output'