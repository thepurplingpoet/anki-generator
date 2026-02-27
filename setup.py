from setuptools import setup

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt", "r") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="anki-deck-generator",
    version="1.0.0",
    description="Generate Anki flashcards from PDF, DOCX, or TXT using AI (Ollama/Claude) or offline",
    long_description=long_description,
    long_description_content_type="text/markdown",
    py_modules=["anki_generator"],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "anki-gen=anki_generator:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Education",
    ],
)
