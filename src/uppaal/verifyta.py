import subprocess
import time

from pathlib import Path

from player.player import WorldView

VERIFYTA_PATH = Path(__file__).parent / 'bin' / 'uppaal'
VERIFYTA_QUERIES_PATH = Path(__file__).parent.parent / 'uppaal' / 'queries'
VERIFYTA_MODELS_PATH = Path(__file__).parent.parent / 'uppaal' / 'models'
VERIFYTA_OUTPUT_DIR_PATH = Path(__file__).parent.parent / 'uppaal' / 'outputdir'


def generate_strategy(wv: WorldView, xml_file_name: str, queries_file_name: str):
    update_xml_file(wv)
    # 1. Update XML file
    # 2. Run uppaal
    # 3. Input strategy to coach

    # Prepared for using uppaal
    # verifyta_path --print-strategies outputdir xml_path queries_dir learning-method?
    command = "{0} --print-strategies {1} {2} {3}".format(VERIFYTA_PATH, VERIFYTA_OUTPUT_DIR_PATH
                                                          , VERIFYTA_MODELS_PATH / xml_file_name
                                                          , VERIFYTA_QUERIES_PATH / queries_file_name)

    # Run uppaal with the arguments given
    verifyta = subprocess.Popen(command, shell=True)

    # Wait for uppaal to finish generating and printing strategy
    while verifyta.poll() is None:
        time.sleep(0.001)

    # todo return strategy??
    return


def update_xml_file(wv):
    pass

# generate_strategy(WorldView(0), 'WindTurbine.xml', 'windTurbineQueries.q')