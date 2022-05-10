import codecs
import os
from os import path

from setuptools import find_packages, setup

here = os.getcwd()

# Get the long description from the README file
with codecs.open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

with open(path.join(here, "requirements.txt")) as f:
    requirements_lines = f.readlines()
install_requires = [r.strip() for r in requirements_lines if "git+" not in r]

with open(path.join(here, "requirements-dev.txt")) as f:
    requirements_lines = f.readlines()
dev_requires = [r.strip() for r in requirements_lines if "git+" not in r]

setup(
    name="pyumi",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    packages=find_packages(exclude=["tests"]),
    url="https://github.com/samuelduchesne/pyumi",
    license="MIT",
    author="Samuel Letellier-Duchesne",
    author_email="samueld@mit.edu",
    description="Create and edit umi projects",
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires=">=3.6",
    install_requires=install_requires,
    extras_require={"dev": dev_requires, "cjio": ["cjio~=0.6.8"]},
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 3 - Alpha",
        # Indicate who your project is intended for
        "Intended Audience :: Science/Research",
        # Pick your license as you wish (should match "license" above)
        "License :: OSI Approved :: MIT License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
