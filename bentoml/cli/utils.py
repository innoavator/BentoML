# Copyright 2019 Atalaya Tech, Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import json
import logging
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

import humanfriendly
import requests
import yaml
from tabulate import tabulate

from bentoml.cli.click_utils import _echo
from bentoml.exceptions import BentoMLException
from bentoml.utils import pb_to_yaml
from bentoml.utils import resolve_bundle_path
from bentoml.utils.tempdir import TempDirectory

logger = logging.getLogger(__name__)


class Spinner:
    def __init__(self, message, delay=0.1):
        self.spinner = itertools.cycle(['-', '/', '|', '\\'])
        self.delay = delay
        self.busy = False
        self._screen_lock = None
        self.thread = None
        self.spinner_visible = False
        sys.stdout.write(message)

    def write_next(self):
        with self._screen_lock:
            if not self.spinner_visible:
                sys.stdout.write(next(self.spinner))
                self.spinner_visible = True
                sys.stdout.flush()

    def remove_spinner(self, cleanup=False):
        with self._screen_lock:
            if self.spinner_visible:
                sys.stdout.write('\b')
                self.spinner_visible = False
                if cleanup:
                    sys.stdout.write(' ')  # overwrite spinner with blank
                    sys.stdout.write('\r')  # move to next line
                sys.stdout.flush()

    def spinner_task(self):
        while self.busy:
            self.write_next()
            time.sleep(self.delay)
            self.remove_spinner()

    def __enter__(self):
        if sys.stdout.isatty():
            self._screen_lock = threading.Lock()
            self.busy = True
            self.thread = threading.Thread(target=self.spinner_task)
            self.thread.start()

    def __exit__(self, exception, value, tb):
        if sys.stdout.isatty():
            self.busy = False
            self.remove_spinner(cleanup=True)
        else:
            sys.stdout.write('\r')


def parse_key_value_pairs(key_value_pairs_str):
    result = {}
    if key_value_pairs_str:
        for key_value_pair in key_value_pairs_str.split(','):
            key, value = key_value_pair.split('=')
            key = key.strip()
            value = value.strip()
            if key in result:
                logger.warning("duplicated key '%s' found string map parameter", key)
            result[key] = value
    return result


def echo_docker_api_result(docker_generator):
    layers = {}
    for line in docker_generator:
        if "stream" in line:
            cleaned = line['stream'].rstrip("\n")
            if cleaned != "":
                yield cleaned
        if "status" in line and line["status"] == "Pushing":
            progress = line["progressDetail"]
            layers[line["id"]] = progress["current"], progress["total"]
            cur, total = zip(*layers.values())
            cur, total = (
                humanfriendly.format_size(sum(cur)),
                humanfriendly.format_size(sum(total)),
            )
            yield f"Pushed {cur} / {total}"
        if "errorDetail" in line:
            error = line["errorDetail"]
            raise BentoMLException(error["message"])


def _print_deployment_info(deployment, output_type):
    if output_type == 'yaml':
        _echo(pb_to_yaml(deployment))
    else:
        from google.protobuf.json_format import MessageToDict

        deployment_info = MessageToDict(deployment)
        if deployment_info['state'] and deployment_info['state']['infoJson']:
            deployment_info['state']['infoJson'] = json.loads(
                deployment_info['state']['infoJson']
            )
        _echo(json.dumps(deployment_info, indent=2, separators=(',', ': ')))


def _format_labels_for_print(labels):
    if not labels:
        return None
    result = [f'{label_key}:{labels[label_key]}' for label_key in labels]
    return '\n'.join(result)


def _format_deployment_age_for_print(deployment_pb):
    if not deployment_pb.created_at:
        # deployments created before version 0.4.5 don't have created_at field,
        # we will not show the age for those deployments
        return None
    else:
        return human_friendly_age_from_datetime(deployment_pb.created_at.ToDatetime())


def human_friendly_age_from_datetime(dt, detailed=False, max_unit=2):
    return humanfriendly.format_timespan(datetime.utcnow() - dt, detailed, max_unit)


def _print_deployments_table(deployments, wide=False):
    from bentoml.yatai.proto.deployment_pb2 import DeploymentState, DeploymentSpec

    table = []
    if wide:
        headers = [
            'NAME',
            'NAMESPACE',
            'PLATFORM',
            'BENTO_SERVICE',
            'STATUS',
            'AGE',
            'LABELS',
        ]
    else:
        headers = [
            'NAME',
            'NAMESPACE',
            'PLATFORM',
            'BENTO_SERVICE',
            'STATUS',
            'AGE',
        ]
    for deployment in deployments:
        row = [
            deployment.name,
            deployment.namespace,
            DeploymentSpec.DeploymentOperator.Name(deployment.spec.operator)
                .lower()
                .replace('_', '-'),
            f'{deployment.spec.bento_name}:{deployment.spec.bento_version}',
            DeploymentState.State.Name(deployment.state.state)
                .lower()
                .replace('_', ' '),
            _format_deployment_age_for_print(deployment),
        ]
        if wide:
            row.append(_format_labels_for_print(deployment.labels))
        table.append(row)
    table_display = tabulate(table, headers, tablefmt='plain')
    _echo(table_display)


def _print_deployments_info(deployments, output_type):
    if output_type == 'table':
        _print_deployments_table(deployments)
    elif output_type == 'wide':
        _print_deployments_table(deployments, wide=True)
    else:
        for deployment in deployments:
            _print_deployment_info(deployment, output_type)


def simple_deploy(cortex_name, cortex_type, region, cortex_url, bento_path: Optional[str] = None,
                  direct_path: Optional[str] = None):
    """
    Zips and deploys your module on AWS
    """
    CORTEX_URL = "{cortex_url}cortex?repository_uri={ecr_uri}&cortex_type={cortex_type}&cortex_name={cortex_name}"
    DOCKER_URL = "{cortex_url}docker?repository_name={repository_name}&region={region}"

    def create_unique_name(name: str):
        name = ''.join([name, "-", str(uuid.uuid4())])[:40]
        if name[:-1] == "-":
            name = name[:-1]
        return name

    def create_zip_file(dir_path: str):
        head, tail = os.path.split(dir_path)
        path = shutil.make_archive(os.path.join(head, create_unique_name(tail)), 'zip', dir_path)
        head, key_name = os.path.split(path)
        return path, key_name

    def create_docker(key_name, zipped_file_path, deploy_region="us-east-1"):
        repository_name = create_unique_name(key_name.split(".")[0])
        docker_url = DOCKER_URL.format(cortex_url=cortex_url, repository_name=repository_name, region=deploy_region)
        files = [
            ('file', (key_name, open(zipped_file_path, 'rb'),
                      'application/zip'))
        ]
        response = requests.request("POST", docker_url, files=files)
        _echo(response.text)
        ecr_uri = json.loads(response.text)['ecr_uri'].split(" ")[-1]
        return ecr_uri

    def create_cortex_api(ecr_uri, cortx_type, cortx_name):
        cortex_endpoint = CORTEX_URL.format(cortex_url=cortex_url, ecr_uri=ecr_uri, cortex_type=cortx_type,
                                            cortex_name=cortx_name)
        response = requests.request("GET", cortex_endpoint)
        backend_api_url = response.text
        backend_api_url = backend_api_url.replace("\n", "")
        backend_api_url = json.loads(backend_api_url)['api_endpoint']
        return backend_api_url

    if bento_path:
        saved_bundle_path = resolve_bundle_path(
            bento_path, None, None
        )
    else:
        saved_bundle_path = direct_path

    _echo("Zipping backend files")
    backend_path, backend_key_name = create_zip_file(saved_bundle_path)
    _echo("Creating docker image for backend")
    backend_docker_uri = create_docker(backend_key_name, backend_path, region)
    _echo("Creating Backend API")
    backend_cortex_uri = create_cortex_api(backend_docker_uri, cortex_type, cortex_name)
    _echo(f"Backend API at : {backend_cortex_uri}")
    return backend_cortex_uri


def complex_deploy(cortex_name, cortex_type, bento_path, region, model_name, model_type, model_url, cortex_url):
    """
    Adds files to module to download models from url and pack it with the python file.
    """
    saved_bundle_path = resolve_bundle_path(
        bento_path, None, None
    )
    with open(os.path.join(saved_bundle_path, "bentoml.yml"), "r") as f:
        graph = yaml.safe_load(f)
    class_name = graph['metadata']['service_name']
    module_name = graph['metadata']['module_name']
    py_version = graph['env']['python_version']

    fastapi_file_script = """\
from fastapi import FastAPI
import requests
import os
import subprocess

app = FastAPI(title="{cortex_name}")

@app.get("/create")
def task():

    try:
        mod=importlib.import_module("{class_name}.{module_name}")
        IrisClassifier=mod.{class_name}
    except Exception as e:
        return "ERROR : %s"%e

    url = "{model_url}"
    try:
        response = requests.get(url)
        if not os.path.exists("tmp_folder"):
            os.mkdir("tmp_folder")
        model_path=os.path.join("tmp_folder","{model_name}")
        with open(model_path,"wb") as f:
            f.write(response.content)
    except Exception as e:
        return "ERROR : %s"%e

    try:
        from bentoml import api, BentoService, artifacts
        from bentoml.frameworks import {model_type}    
        model={model_type}("{model_name_only}")
        clf=model.load("tmp_folder").get()
    except Exception as e:
        return "ERROR : %s"%e

    try:
        bento_class={class_name}()
        bento_class.pack("model",clf)
        bento_class.save()
    except Exception as e:
        return "ERROR : %s"%e

    try:
        res=subprocess.check_output(["bentoml","deploy","{class_name}:latest","--region","{region}","--cortex-name","{cortex_name}","--cortex-type","{cortex_type}"],stdout=subprocess.PIPE)
        return res.decode()
    except Exception as e:
        return "ERROR : %s"%e
"""

    ffs = fastapi_file_script.format(
        class_name=class_name,
        module_name=module_name,
        cortex_name=cortex_name,
        cortex_type=cortex_type,
        region=region,
        model_name=model_name,
        model_name_only=model_name.split(".")[0],
        model_type=model_type,
        model_url=model_url
    )

    dockerfile = """\
FROM python:{py_version}

COPY requirements.txt /
RUN pip install -r ./requirements.txt --no-cache-dir

COPY . /

CMD ["uvicorn","bento_script:app","--reload","--port","5000","--host","0.0.0.0"]
"""
    dockerfile = dockerfile.format(py_version=py_version)

    with open(os.path.join(saved_bundle_path, "bento_script.py"), "w") as f:
        f.write(ffs)
    with open(os.path.join(saved_bundle_path, "Dockerfile"), "w") as f:
        f.write(dockerfile)

    simple_deploy(cortex_name, cortex_type, bento_path, region, cortex_url)


def create_python_file(api_endpoints, region, cortex_url):
    """
    Creates a python file to hit all endpoints in the pipeline.
    """

    def create_unique_name(name: str):
        name = ''.join([name, "-", str(uuid.uuid4())])[:40]
        if name[:-1] == "-":
            name = name[:-1]
        return name

    python_script = """\
from fastapi import FastAPI
import requests

app = FastAPI(title="Bundled Requests")

@app.get("/")
def pipeline():
    api_endpoints={api_endpoints}

    for api in api_endpoints:
        try:
            response = requests.get(api)
            if response.status_code!=200:
                return "ERROR : %s"%response.text
        except Exception as e:
            return "ERROR : %s"%e
    return "Pipeline completed!"
    """
    dockerfile = """\
FROM python:3.8-slim

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--reload","--host","0.0.0.0","--port","5000"]
    """
    requirements = """\
fastapi
uvicorn
requests
    """
    with TempDirectory() as tmp_dir:
        python_script = python_script.format(api_endpoints=api_endpoints)
        with open(os.path.join(tmp_dir, "main.py"), "w") as f:
            f.write(python_script)
        with open(os.path.join(tmp_dir, "Dockerfile"), "w") as f:
            f.write(dockerfile)
        with open(os.path.join(tmp_dir, "requirements.txt"), "w") as f:
            f.write(requirements)
        api_endpoint = simple_deploy(cortex_name=create_unique_name("pipeline"), cortex_type="RealtimeAPI",
                                     region=region,
                                     direct_path=tmp_dir,
                                     cortex_url=cortex_url)
        return api_endpoint
