from setuptools import find_packages, setup

setup(
    name="rest-clients-py",
    version="0.3.0",
    description="Notes and small building blocks for consuming REST APIs from Python",
    author="Avery Lane",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    python_requires=">=3.7",
    install_requires=[],  # the core runs on the standard library alone
    extras_require={"requests": ["requests>=2.24.0"]},
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
