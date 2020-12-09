import os
from os import path

from setuptools import setup

here = os.getcwd()

with open(path.join(here, "requirements.txt")) as f:
    requirements_lines = f.readlines()
install_requires = [r.strip() for r in requirements_lines if "git+" not in r]

setup(
    name="pyumi",
    version="1.0",
    packages=["pyumi"],
    url="",
    license="MIT",
    author="Samuel Letellier-Duchesne",
    author_email="samueld@mit.edu",
    description="Create and edit umi projects",
    python_requires="==3.7.*",
    install_requires=install_requires + ["epw @ https://github.com/building-energy/epw/archive/master.zip"],
)
