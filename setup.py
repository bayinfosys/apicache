from setuptools import setup, find_packages

setup(
    name="apicache",
    version="0.1.0",
    description="A lightweight, data-aware API proxy-cache for reproducible workflows and rate-limit resilience.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Edward Grundy",
    author_email="ed@bayis.co.uk",
    url="https://github.com/bayinfosys/apicache",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "requests"
    ],
    python_requires=">=3.7",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
