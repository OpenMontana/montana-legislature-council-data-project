# Scraper - Getting Started

Use this doc to get started with testing / running the scraper from your local machine.

1. Use Python >= 3.10

    ```sh
    python3 --version
    ```

    The version should be something like `Python 3.10.6` (or newer).

2. Set up a virtualenv

    From the root dir of this project:

    ```sh
    python3 -m venv ./env
    ```

    This creates a virtual environment so that the project dependencies can be isolated from the rest of your system.

3. Activate the virtual environment

    From the root dir of this project:

    ```sh
    source ./env/bin/activate
    ```

    Once the virtualenv is activated, you can verify that the local `python` is in your shell PATH.

    ```sh
    which python
    ```

    The path for `python` should be something like...

    `/path/to/this/project/env/bin/python`

4. Install dependencies

    From the root of this project, install the requirements defined in `./python`. (See `./python/setup.py` for the full requirements.)

    ```sh
    pip install ./python/
    ```

5. Run the scraper

    After the dependencies are installed, you can run the scraper:

    ```sh
    python python/cdp_montana_legislature_backend/scraper.py
    ```

    The scraper supports two arguments to set the datetime span of the events that will be gathered. Use the `-h` flag to see the usage.
