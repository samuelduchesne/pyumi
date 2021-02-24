"""Pyumi package, a tool to work with UMI projects in python."""
import logging

from pyumi.umi_project import UmiProject

logging.basicConfig(level=logging.INFO)

__all__ = ["UmiProject"]
