"""a JupyterLite addon for creating the env for xeus-nelson"""
import json
import os
from pathlib import Path
import requests
import shutil
from subprocess import check_call, run, DEVNULL
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import yaml

from traitlets import List, Unicode

from empack.file_packager import pack_environment
from empack.file_patterns import PkgFileFilter, pkg_file_filter_from_yaml

from jupyterlite_core.constants import (
    SHARE_LABEXTENSIONS,
    LAB_EXTENSIONS,
    JUPYTERLITE_JSON,
    UTF8,
    FEDERATED_EXTENSIONS,
)
from jupyterlite_core.addons.federated_extensions import (
    FederatedExtensionAddon,
    ENV_EXTENSIONS,
)

from .build import build_and_pack_emscripten_env

JUPYTERLITE_XEUS_NELSON = "@jupyterlite/xeus-nelson-kernel"


class PackagesList(List):
    def from_string(self, s):
        return s.split(",")


class XeusPythonEnv(FederatedExtensionAddon):

    __all__ = ["post_build"]

    xeus_nelson_version = Unicode().tag(
        config=True, description="The xeus-nelson version to use"
    )

    empack_config = Unicode(
        None,
        config=True,
        allow_none=True,
        description="The path or URL to the empack config file",
    )

    packages = PackagesList([]).tag(
        config=True,
        description="A comma-separated list of packages to install in the xeus-nelson env",
    )

    environment_file = Unicode(
        "environment.yml",
        config=True,
        description='The path to the environment file. Defaults to "environment.yml"',
    )

    def __init__(self, *args, **kwargs):
        super(XeusPythonEnv, self).__init__(*args, **kwargs)

        self.cwd = TemporaryDirectory()

    def post_build(self, manager):
        """yield a doit task to create the emscripten-32 env and grab anything we need from it"""
        # Install the jupyterlite-xeus-nelson ourselves
        for pkg_json in self.env_extensions(ENV_EXTENSIONS):
            pkg_data = json.loads(pkg_json.read_text(**UTF8))
            if pkg_data.get("name") == JUPYTERLITE_XEUS_NELSON:
                yield from self.safe_copy_extension(pkg_json)

        env_prefix = build_and_pack_emscripten_env(
            xeus_nelson_version=self.xeus_nelson_version,
            packages=self.packages,
            environment_file=Path(self.manager.lite_dir) / self.environment_file,
            empack_config=self.empack_config,
            output_path=self.cwd.name,
        )

        # Find the federated extensions in the emscripten-env and install them
        for pkg_json in self.env_extensions(env_prefix / SHARE_LABEXTENSIONS):
            yield from self.safe_copy_extension(pkg_json)

        # TODO Currently we're shamelessly overwriting the
        # nelson_data.{js,data} into the jupyterlite-xeus-nelson labextension.
        # We should really find a nicer way.
        # (make jupyterlite-xeus-nelson extension somewhat configurable?)
        dest = self.output_extensions / "@jupyterlite" / "xeus-nelson-kernel" / "static"
        
        # copy *.data/*.js for all side packages
        for item in Path(self.cwd.name) .iterdir():
            if item.suffix == ".data":

                file = item.name 
                yield dict(
                    name=f"xeus:copy:{file}",
                    actions=[(self.copy_one, [item, dest / file])],
                )

                js_item  = Path(self.cwd.name) / (str(item.stem) + '.js')
                js_file = js_item.name 
                yield dict(
                    name=f"xeus:copy:{js_file}",
                    actions=[(self.copy_one, [js_item, dest / js_file])],
                )


        for file in [
            "nelson_data.js",
            "xnelson_wasm.js",
            "xnelson_wasm.wasm",
        ]:
            yield dict(
                name=f"xeus:copy:{file}",
                actions=[(self.copy_one, [Path(self.cwd.name) / file, dest / file])],
            )

        jupyterlite_json = manager.output_dir / JUPYTERLITE_JSON
        lab_extensions_root = manager.output_dir / LAB_EXTENSIONS
        lab_extensions = self.env_extensions(lab_extensions_root)

        yield dict(
            name="patch:xeus",
            doc=f"ensure {JUPYTERLITE_JSON} includes the federated_extensions",
            file_dep=[*lab_extensions, jupyterlite_json],
            actions=[(self.patch_jupyterlite_json, [jupyterlite_json])],
        )

    def safe_copy_extension(self, pkg_json):
        """Copy a labextension, and overwrite it
        if it's already in the output
        """
        pkg_path = pkg_json.parent
        stem = json.loads(pkg_json.read_text(**UTF8))["name"]
        dest = self.output_extensions / stem
        file_dep = [
            p
            for p in pkg_path.rglob("*")
            if not (p.is_dir() or self.is_ignored_sourcemap(p.name))
        ]

        yield dict(
            name=f"xeus:copy:ext:{stem}",
            file_dep=file_dep,
            actions=[(self.copy_one, [pkg_path, dest])],
        )

    def dedupe_federated_extensions(self, config):
        if FEDERATED_EXTENSIONS not in config:
            return

        named = {}

        # Making sure to dedupe extensions by keeping the most recent ones
        for ext in config[FEDERATED_EXTENSIONS]:
            if os.path.exists(self.output_extensions / ext["name"] / ext["load"]):
                named[ext["name"]] = ext

        config[FEDERATED_EXTENSIONS] = sorted(named.values(), key=lambda x: x["name"])
