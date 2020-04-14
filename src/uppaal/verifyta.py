import subprocess
import time
import re
from os import fdopen, remove

from shutil import copymode, move
from tempfile import mkstemp

from coach.world_objects_coach import WorldViewCoach, PlayerViewCoach
from uppaal.uppaal_model import UPPAAL_MODEL
from uppaal import VERIFYTA_MODELS_PATH, VERIFYTA_OUTPUT_DIR_PATH, VERIFYTA_QUERIES_PATH, VERIFYTA_PATH


def generate_strategy(wv: WorldViewCoach):
    applicable_strat = find_applicable_strat(wv)
    if applicable_strat is None:
        return
    xml_file_name = applicable_strat + ".xml"
    queries_file_name = applicable_strat + ".q"

    # Create model
    model = UPPAAL_MODEL(xml_file_name)
    # Update model according to world view. Only works for SimplePassingModel currently.
    _update_model(wv, model, xml_file_name)

    # Update queries files with the right path
    path_to_strat_file = _update_queries_write_path(str(VERIFYTA_QUERIES_PATH / queries_file_name))

    # Generate command to generate strategy
    # verifyta_path --print-strategies outputdir xml_path queries_dir learning-method?
    command = "{0} {1} {2}".format(VERIFYTA_PATH, VERIFYTA_MODELS_PATH / xml_file_name
                                   , VERIFYTA_QUERIES_PATH / queries_file_name)

    # Run uppaal verifyta command line tool
    verifyta = subprocess.Popen(command, shell=True)

    # Wait for uppaal to finish generating and printing strategy
    while verifyta.poll() is None:
        time.sleep(0.001)

    # 3. Input strategy to coach
    passing_list = parse_passing_strat(path_to_strat_file)
    # todo create representation of strategy and input to coach. Maybe return as object? - Philip
    return


def find_applicable_strat(wv):
    # Simple passing model is only applicable if 1 player is in possession of the ball
    play_in_poss: int = 0
    for play in wv.players:
        if play.has_ball:
            play_in_poss += 1

    if play_in_poss == 1:
        return "SimplePassingModel"

    return None

def parse_passing_strat(path_to_strat_file):
    strat_string = ""
    with open(path_to_strat_file, 'r') as f:
        for l in f:
            strat_string = strat_string + l

    index_to_transition_dict: {} = _extract_transition_dict(strat_string)

    statevars: [] = _extract_statevars(strat_string)

    return []


def _update_queries_write_path(query_path):
    with open(query_path, 'r') as f:
        for l in f:
            stripped_line = l.strip()
            if stripped_line.startswith("saveStrategy"):
                strat = re.search(',.*\)', stripped_line)
                strat_name = strat.group(0)[1:-1]
                new_strat_file_name = re.search('/[^/]*"', stripped_line)
                strat_file_name = new_strat_file_name.group(0)[1:-1]
                newline = 'saveStrategy("' + str(
                    VERIFYTA_OUTPUT_DIR_PATH / strat_file_name) + '",' + strat_name + ')' + '\n'
                _replace_in_file(query_path, l, newline)
                # This does not work for more than one saveStrategy call
                break

    return str(VERIFYTA_OUTPUT_DIR_PATH / strat_file_name)


def _replace_in_file(file_path, pattern, subst):
    # Create temp file
    fh, abs_path = mkstemp()
    with fdopen(fh, 'w') as new_file:
        with open(file_path) as old_file:
            for line in old_file:
                new_file.write(line.replace(pattern, subst))
    # Copy the file permissions from the old file to the new file
    copymode(file_path, abs_path)
    # Remove original file
    remove(file_path)
    # Move new file
    move(abs_path, file_path)


def _update_model(wv, model: UPPAAL_MODEL, xml_file_name):
    '''
    UPPAAL current setup
    player0 = TeamPlayer(0, 10, 10, true);
    player1 = TeamPlayer(1, 15, 15, false);
    player2 = TeamPlayer(2, 45, 10, false);
    player3 = TeamPlayer(3, 30, 10, false);
    player4 = TeamPlayer(4, 60, 10, false);
    '''

    five_closest_players: [PlayerViewCoach] = wv.get_closest_team_players_to_ball(5)
    # Arguments:
    # const player_id_t id, const int pos_x, const int pos_y, bool has_ball
    for play in five_closest_players:
        if play.has_ball:
            model.set_arguments(play.num, [play.num, play.coord.pos_x, play.coord.pos_y, 'true'])
        else:
            model.set_arguments(play.num, [play.num, play.coord.pos_x, play.coord.pos_y, 'false'])

    model.save_xml_file(xml_file_name)


def _extract_transition_dict(strat_string):
    trans_dict = {}
    # Get actions part of strategy
    act_text = re.search(r'"actions":\{.*\},"s', strat_string, re.DOTALL)
    # Remove "actions":{ and },"s
    act_text = act_text.group(0)[11:-4].strip()
    # Create list by separating at commas
    act_lines = act_text.split('\n')
    # Strip all elements from empty spaces and quotes
    act_lines = [w.strip() for w in act_lines]

    for l in act_lines:
        matches = re.findall(r'"[^\"]*"', l, re.DOTALL)
        index = str(matches[0]).replace('"', "")
        value = str(matches[1]).replace('"', "")
        trans_dict[index] = value

    return trans_dict


def _extract_statevars(strat_string):
    # Get statevars part of strategy
    statevars = re.search(r'"statevars":\[[^\]]*\]', strat_string, re.DOTALL)
    # Remove "statevars":[ and ]
    statevars = statevars.group(0).split('[')[1].split(']')[0]
    # Create list by separating at commas
    statevars = statevars.split(',')
    # Strip all elements from empty spaces and quotes
    statevars = [w.strip()[1:-1] for w in statevars]

    return statevars


generate_strategy(WorldViewCoach(0, "team1"), 'SimplePassingModel.xml', 'SimplePassingModel.q')
