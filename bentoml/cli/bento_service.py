import argparse
import json
import re
import sys

import click
import psutil
from dependency_injector.wiring import Provide, inject

from bentoml import __version__
from bentoml.cli.click_utils import (
    CLI_COLOR_SUCCESS,
    BentoMLCommandGroup,
    _echo,
    conditional_argument,
)
from bentoml.cli.utils import Spinner
from bentoml.configuration.containers import BentoMLContainer
from bentoml.saved_bundle import (
    load_bento_service_api,
    load_bento_service_metadata,
    load_from_dir,
)
from bentoml.server import start_dev_server, start_prod_server
from bentoml.server.open_api import get_open_api_spec_json
from bentoml.utils import ProtoMessageToDict, resolve_bundle_path
from bentoml.utils.docker_utils import validate_tag
from bentoml.utils.lazy_loader import LazyLoader
from bentoml.yatai.client import get_yatai_client

try:
    import click_completion

    click_completion.init()
    shell_types = click_completion.DocumentedChoice(click_completion.core.shells)
except ImportError:
    # click_completion package is optional to use BentoML cli,
    click_completion = None
    shell_types = click.Choice(['bash', 'zsh', 'fish', 'powershell'])

yatai_proto = LazyLoader('yatai_proto', globals(), 'bentoml.yatai.proto')


def add_options(options):
    def _add_options(func):
        for option in reversed(options):
            func = option(func)
        return func

    return _add_options


def escape_shell_params(param):
    k, v = param.split("=")
    v = re.sub(r"([^a-zA-Z0-9])", r"\\\1", v)
    return "{}={}".format(k, v)


@inject
def create_bento_service_cli(
        pip_installed_bundle_path: str = None,
        default_yatai_url: str = None,
        default_port: int = Provide[BentoMLContainer.config.bento_server.port],
        default_enable_microbatch: bool = Provide[
            BentoMLContainer.config.bento_server.microbatch.enabled
        ],
        default_mb_max_batch_size: int = Provide[
            BentoMLContainer.config.bento_server.microbatch.max_batch_size
        ],
        default_mb_max_latency: int = Provide[
            BentoMLContainer.config.bento_server.microbatch.max_latency
        ],
        default_run_with_ngrok: bool = Provide[
            BentoMLContainer.config.bento_server.ngrok.enabled
        ],
        default_enable_swagger: bool = Provide[
            BentoMLContainer.config.bento_server.swagger.enabled
        ],
        default_workers: int = Provide[BentoMLContainer.config.bento_server.workers],
        default_microbatch_workers: int = Provide[
            BentoMLContainer.config.bento_server.microbatch.workers
        ],
        default_timeout: int = Provide[BentoMLContainer.config.bento_server.timeout],
):
    # pylint: disable=unused-variable

    batch_options = [
        click.option(
            '--enable-microbatch/--disable-microbatch',
            default=default_enable_microbatch,
            help="Run API server with micro-batch enabled.",
            envvar='BENTOML_ENABLE_MICROBATCH',
        ),
        click.option(
            '--mb-max-batch-size',
            type=click.INT,
            help="Specify micro batching maximal batch size.",
            envvar='BENTOML_MB_MAX_BATCH_SIZE',
            default=default_mb_max_batch_size,
        ),
        click.option(
            '--mb-max-latency',
            type=click.INT,
            help="Specify micro batching maximal latency in milliseconds.",
            envvar='BENTOML_MB_MAX_LATENCY',
            default=default_mb_max_latency,
        ),
    ]

    @click.group(cls=BentoMLCommandGroup)
    @click.version_option(version=__version__)
    def bentoml_cli():
        """
        BentoML CLI tool
        """

    # Example Usage: bentoml run {API_NAME} {BUNDLE_PATH} --input ...
    @bentoml_cli.command(
        help="Run a API defined in saved BentoService bundle from command line",
        short_help="Run API function",
        context_settings=dict(ignore_unknown_options=True, allow_extra_args=True),
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.argument("api_name", type=click.STRING)
    @click.argument('run_args', nargs=-1, type=click.UNPROCESSED)
    def run(api_name, run_args, bento=None):
        parser = argparse.ArgumentParser()
        parser.add_argument('--yatai-url', type=str, default=default_yatai_url)
        parsed_args, _ = parser.parse_known_args(run_args)
        yatai_url = parsed_args.yatai_url
        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        api = load_bento_service_api(saved_bundle_path, api_name)
        exit_code = api.handle_cli(run_args)
        sys.exit(exit_code)

    # Example Usage: bentoml info {BUNDLE_PATH}
    @bentoml_cli.command(
        help="List all APIs defined in the BentoService loaded from saved bundle",
        short_help="List APIs",
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Remote YataiService URL. Optional. '
             'Example: "--yatai-url http://localhost:50050"',
    )
    def info(bento=None, yatai_url=None):
        """
        List all APIs defined in the BentoService loaded from saved bundle
        """
        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        bento_service_metadata_pb = load_bento_service_metadata(saved_bundle_path)
        output = json.dumps(ProtoMessageToDict(bento_service_metadata_pb), indent=2)
        _echo(output)

    # Example usage: bentoml open-api-spec {BUNDLE_PATH}
    @bentoml_cli.command(
        name="open-api-spec",
        help="Display API specification JSON in Open-API format",
        short_help="Display OpenAPI/Swagger JSON specs",
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Remote YataiService URL. Optional. '
             'Example: "--yatai-url http://localhost:50050"',
    )
    def open_api_spec(bento=None, yatai_url=None):
        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        bento_service = load_from_dir(saved_bundle_path)

        _echo(json.dumps(get_open_api_spec_json(bento_service), indent=2))

    # Example Usage: bentoml serve {BUNDLE_PATH} --port={PORT}
    @bentoml_cli.command(
        help="Start a dev API server serving specified BentoService",
        short_help="Start local dev API server",
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.option(
        "--port",
        type=click.INT,
        default=default_port,
        help="The port to listen on for the REST api server, default is 5000",
        envvar='BENTOML_PORT',
    )
    @add_options(batch_options)
    @click.option(
        '--run-with-ngrok',
        is_flag=True,
        default=default_run_with_ngrok,
        help="Use ngrok to relay traffic on a public endpoint to this "
             "API server on localhost",
        envvar='BENTOML_ENABLE_NGROK',
    )
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Remote YataiService URL. Optional. '
             'Example: "--yatai-url http://localhost:50050"',
    )
    @click.option(
        '--enable-swagger/--disable-swagger',
        is_flag=True,
        default=default_enable_swagger,
        help="Run API server with Swagger UI enabled",
        envvar='BENTOML_ENABLE_SWAGGER',
    )
    def serve(
            port,
            bento,
            enable_microbatch,
            mb_max_batch_size,
            mb_max_latency,
            run_with_ngrok,
            yatai_url,
            enable_swagger,
    ):
        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        start_dev_server(
            saved_bundle_path,
            port=port,
            enable_microbatch=enable_microbatch,
            mb_max_batch_size=mb_max_batch_size,
            mb_max_latency=mb_max_latency,
            run_with_ngrok=run_with_ngrok,
            enable_swagger=enable_swagger,
        )

    # Example Usage: bentoml deploy {BUNDLE_PATH}
    @bentoml_cli.command(
        help="Deploy your module on AWS lambda.",
        short_help="Deploy your endpoint on AWS.",
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Remote YataiService URL. Optional. '
             'Example: "--yatai-url http://localhost:50050"',
    )
    def deploy(
            bento,
            yatai_url,
    ):
        import os
        import json
        import shutil
        import requests
        import uuid

        def create_unique_name(name):
            return ''.join([name, "-", str(uuid.uuid4())])

        S3_URL = "https://nwkvz4at57.execute-api.eu-west-1.amazonaws.com/v1/s3uri?region={region}&key_name={key_name}"
        DOCKER_URL = "https://nwkvz4at57.execute-api.eu-west-1.amazonaws.com/v1/docker?repository_name={repository_name}&region={region}&s3_uri={s3_uri}"

        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )
        # Zip the files
        dir_path = saved_bundle_path
        head, tail = os.path.split(dir_path)
        path = shutil.make_archive(os.path.join(head, create_unique_name(tail)), 'zip', dir_path)
        head, key_name = os.path.split(path)
        _echo("Done zipping")

        # Send to S3
        get_presigned_url = S3_URL.format(region="eu-west-1", key_name=key_name)
        response = requests.get(get_presigned_url)
        presigned_url = json.loads(response.text)["url"]
        with open(path, "rb") as f:
            file_obj = f.read()
        response = requests.put(presigned_url, data=file_obj)
        if response.status_code != 200:
            raise Exception(f"ERROR: status code: {response.status_code}; reason : {response.text}")
        bucket_name = presigned_url.split("/")[2].split(".")[0]
        s3_uri = f"s3://{bucket_name}/{key_name}"
        _echo("File Uploaded to s3")

        # Create Docker
        repository_name = create_unique_name("docker")
        docker_url = DOCKER_URL.format(repository_name=repository_name, region="eu-west-1", s3_uri=s3_uri)
        response = requests.post(docker_url)
        if response.status_code != 200:
            raise Exception(f"ERROR: status code: {response.status_code}; reason : {response.text}")
        result = json.loads(response.text)
        _echo(result)

    # Example Usage: bentoml save-direct --path={PATH}
    @bentoml_cli.command(
        help="Generate and save the entire module from a python file",
        short_help="Save module from path",
    )
    @click.option(
        '--path',
        type=click.STRING,
        default=".",
        help='The path to .py file'
             'Example: "--path D:\PythonProjects\HelloWorld.py"'
             'Example: "--path HelloWorld.py"',
    )
    def save_direct(
            path
    ):
        if path[-2:] != "py":
            raise Exception("the file is not a python file")

        import os
        import importlib
        import inspect
        from bentoml import BentoService
        complete_path = os.path.join(os.getcwd(), path)
        head, module_name = os.path.split(complete_path)
        sys.path.append(head)
        module_name = module_name[:-3]
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            raise Exception(f"Couldn't import module:", e)

        count = 0
        class_names = []
        for name, obj in inspect.getmembers(module):
            try:
                if inspect.isclass(obj) and issubclass(obj, BentoService) and \
                        getattr(obj, '__module__', None).split(".")[0] != "bentoml":
                    count += 1
                    class_names.append(obj.__name__)
            except:
                pass
        _echo(f"Found {count} classes to save")
        for i in class_names:
            try:
                init = getattr(module, i)
                init().save()
            except Exception as e:
                _echo(f"Couldn't save {i}")
        _echo("Saved all the necessary modules.")

    # Example Usage:
    # bentoml serve-gunicorn {BUNDLE_PATH} --port={PORT} --workers={WORKERS}
    @bentoml_cli.command(
        help="Start a production API server serving specified BentoService",
        short_help="Start production API server",
    )
    @conditional_argument(pip_installed_bundle_path is None, "bento", type=click.STRING)
    @click.option(
        "-p",
        "--port",
        type=click.INT,
        default=default_port,
        help="The port to listen on for the REST api server, default is 5000",
        envvar='BENTOML_PORT',
    )
    @click.option(
        "-w",
        "--workers",
        type=click.INT,
        default=default_workers,
        help="Number of workers will start for the gunicorn server",
        envvar='BENTOML_GUNICORN_WORKERS',
    )
    @click.option(
        "--timeout",
        type=click.INT,
        default=default_timeout,
        help="Number of seconds for an API server request to timeout",
    )
    @add_options(batch_options)
    @click.option(
        '--microbatch-workers',
        type=click.INT,
        default=default_microbatch_workers,
        help="Number of micro-batch request dispatcher workers",
        envvar='BENTOML_MICROBATCH_WORKERS',
    )
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Remote YataiService URL. Optional. '
             'Example: "--yatai-url http://localhost:50050"',
    )
    @click.option(
        '--enable-swagger/--disable-swagger',
        is_flag=True,
        default=default_enable_swagger,
        help="Run API server with Swagger UI enabled",
        envvar='BENTOML_ENABLE_SWAGGER',
    )
    def serve_gunicorn(
            port,
            workers,
            timeout,
            bento,
            enable_microbatch,
            mb_max_batch_size,
            mb_max_latency,
            microbatch_workers,
            yatai_url,
            enable_swagger,
    ):
        if not psutil.POSIX:
            _echo(
                "The `bentoml serve-gunicorn` command is only supported on POSIX. "
                "On windows platform, use `bentoml serve` for local API testing and "
                "docker for running production API endpoint: "
                "https://docs.docker.com/docker-for-windows/ "
            )
            return

        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        start_prod_server(
            saved_bundle_path,
            port=port,
            workers=workers,
            timeout=timeout,
            enable_microbatch=enable_microbatch,
            enable_swagger=enable_swagger,
            mb_max_batch_size=mb_max_batch_size,
            mb_max_latency=mb_max_latency,
            microbatch_workers=microbatch_workers,
        )

    @bentoml_cli.command(
        help="Install shell command completion",
        short_help="Install shell command completion",
    )
    @click.option(
        '--append/--overwrite',
        help="Append the completion code to the file",
        default=None,
    )
    @click.argument('shell', required=False, type=shell_types)
    @click.argument('path', required=False)
    def install_completion(append, shell, path):
        if click_completion:
            # click_completion package is imported
            shell, path = click_completion.core.install(
                shell=shell, path=path, append=append
            )
            click.echo('%s completion installed in %s' % (shell, path))
        else:
            click.echo(
                "'click_completion' is required for BentoML auto-completion, "
                "install it with `pip install click_completion`"
            )

    @bentoml_cli.command(
        help='Containerizes given Bento into a ready-to-use Docker image.',
        short_help="Containerizes given Bento into a ready-to-use Docker image",
    )
    @click.argument("bento", type=click.STRING)
    @click.option('--push', is_flag=True)
    @click.option(
        '-t',
        '--tag',
        help="Optional image tag. If not specified, Bento will generate one from "
             "the name of the Bento.",
        required=False,
        callback=validate_tag,
    )
    @click.option(
        '--build-arg', multiple=True, help="pass through docker image build arguments"
    )
    @click.option(
        '--yatai-url',
        type=click.STRING,
        default=default_yatai_url,
        help='Specify the YataiService for running the containerization, default to '
             'the Local YataiService with local docker daemon. Example: '
             '"--yatai-url http://localhost:50050"',
    )
    def containerize(bento, push, tag, build_arg, yatai_url):
        """Containerize specified BentoService.

        BENTO is the target BentoService to be containerized, referenced by its name
        and version in format of name:version. For example: "iris_classifier:v1.2.0"

        `bentoml containerize` command also supports the use of the `latest` tag
        which will automatically use the last built version of your Bento.

        You can provide a tag for the image built by Bento using the
        `--tag` flag. Additionally, you can provide a `--push` flag,
        which will push the built image to the Docker repository specified by the
        image tag.

        You can also prefixing the tag with a hostname for the repository you wish
        to push to.
        e.g. `bentoml containerize IrisClassifier:latest --push --tag
        repo-address.com:username/iris` would build a Docker image called
        `username/iris:latest` and push that to docker repository at repo-addres.com.

        By default, the `containerize` command will use the current credentials
        provided by Docker daemon.
        """
        saved_bundle_path = resolve_bundle_path(
            bento, pip_installed_bundle_path, yatai_url
        )

        _echo(f"Found Bento: {saved_bundle_path}")

        bento_metadata = load_bento_service_metadata(saved_bundle_path)
        bento_tag = f'{bento_metadata.name}:{bento_metadata.version}'
        yatai_client = get_yatai_client(yatai_url)
        docker_build_args = {}
        if build_arg:
            for arg in build_arg:
                key, value = arg.split("=", 1)
                docker_build_args[key] = value
        if yatai_url is not None:
            spinner_message = f'Sending containerize RPC to YataiService at {yatai_url}'
        else:
            spinner_message = (
                f'Containerizing {bento_tag} with local YataiService and docker '
                f'daemon from local environment'
            )
        with Spinner(spinner_message):
            tag = yatai_client.repository.containerize(
                bento=bento_tag, tag=tag, build_args=docker_build_args, push=push,
            )
            _echo(f'Build container image: {tag}', CLI_COLOR_SUCCESS)

    # pylint: enable=unused-variable
    return bentoml_cli
