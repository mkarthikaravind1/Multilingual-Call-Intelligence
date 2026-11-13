from setuptools import setup, find_packages

setup(
    name="call-analysis-evalkit",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.28.0",
        "websockets>=13.0",
    ],
)

