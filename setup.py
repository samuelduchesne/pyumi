import os
from os import path

from setuptools import find_packages, setup

here = os.getcwd()

with open(path.join(here, "requirements.txt")) as f:
    requirements_lines = f.readlines()
install_requires = [r.strip() for r in requirements_lines if "git+" not in r]

with open(path.join(here, "requirements-dev.txt")) as f:
    requirements_lines = f.readlines()
dev_requires = [r.strip() for r in requirements_lines if "git+" not in r]

setup(
    name="pyumi",
    version="1.0",
    packages=find_packages(exclude=["tests"]),
    url="",
    license="MIT",
    author="Samuel Letellier-Duchesne",
    author_email="samueld@mit.edu",
    description="Create and edit umi projects",
    python_requires="==3.7.*",
    install_requires=install_requires,
    extras_require={"dev": dev_requires},
)
