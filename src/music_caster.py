VERSION = latest_version = '4.85.1'
UPDATE_MESSAGE = """
[Feature] Locate tracks in playlists
[Feature] Added option to remember selected folder
[HELP] Could use some translators
""".strip()
import argparse
from contextlib import suppress
import multiprocessing as mp
import os
from queue import Queue
# noinspection PyUnresolvedReferences
import re
# noinspection PyUnresolvedReferences
import requests
import sys
from subprocess import Popen, PIPE, DEVNULL


parser = argparse.ArgumentParser(description='Music Caster')
parser.add_argument('--debug', '-d', default=False, action='store_true', help='allows > 1 instance + no info sent')
parser.add_argument('--queue', '-q', default=False, action='store_true', help='paths are queued')
parser.add_argument('--playnext', '-n', default=False, action='store_true', help='paths are added to next up')
parser.add_argument('--urlprotocol', '-p', default=False, action='store_true', help='launched using uri protocol')
parser.add_argument('--update', '-u', default=False, action='store_true', help='allow updating')
parser.add_argument('--exit', '-x', default=False, action='store_true',
                    help='exits any existing instance (including self)')
parser.add_argument('uris', nargs='*', default=[], help='list of files/dirs/playlists/urls to play/queue')
# freeze_support() adds the following
parser.add_argument('--multiprocessing-fork', default=False, action='store_true')
# the following option is used in the build script since MC doesn't run as a CLI
parser.add_argument('--version', '-v', default=False, action='store_true', help='returns the version')
args = parser.parse_args()
# if from url protocol, re-parse arguments
if args.urlprotocol:
    new_args = args.uris[0].replace('music-caster://', '', 1).replace('music-caster:', '')
    if new_args: new_args = new_args.split(';')
    args = parser.parse_args(new_args)
if args.version:
    print(VERSION)
    sys.exit()
DEBUG = args.debug
UNINSTALLER = 'unins000.exe'
WAIT_TIMEOUT, IS_FROZEN = 15, getattr(sys, 'frozen', False)
daemon_commands, tray_process_queue, uris_to_scan = mp.Queue(), mp.Queue(), Queue()


def get_running_processes(look_for=''):
    cmd = f'tasklist /NH /FI "IMAGENAME eq {look_for}"' if look_for else f'tasklist /NH'
    p = Popen(cmd, shell=True, stdout=PIPE, stdin=DEVNULL, stderr=DEVNULL, text=True)
    p.stdout.readline()
    for task in iter(lambda: p.stdout.readline().strip(), ''):
        m = re.match(r'(.+?) +(\d+) (.+?) +(\d+) +(\d+.* K).*', task)
        if m is not None:
            yield {'name': m.group(1), 'pid': int(m.group(2)), 'session_name': m.group(3),
                   'session_num': m.group(4), 'mem_usage': m.group(5)}


def is_already_running(look_for='Music Caster.exe', threshold=1):
    for process in get_running_processes(look_for=look_for):
        if process['name'] == look_for:
            threshold -= 1
            if threshold < 0: return True
    return False


def system_tray(main_queue: mp.Queue, child_queue: mp.Queue):
    """
    To be called from the first process.
    This process will take care of reading the tray
    """
    import PySimpleGUIWx as SgWx
    from b64_images import UNFILLED_ICON
    _tray = SgWx.SystemTray(menu=['', []], data_base64=UNFILLED_ICON, tooltip='Music Caster [LOADING]')
    _tray_item = ''
    exit_key = 'Exit'
    while _tray_item is not {None, exit_key}:
        _tray_item = _tray.Read(timeout=200)
        main_queue.put(_tray_item)
        with suppress(IndexError):
            exit_key = _tray.Menu[-1][-1]
        if _tray_item == exit_key:
            _tray.hide()
            _tray.close()
        while not child_queue.empty():
            tray_command = child_queue.get()
            tray_method = tray_command['method']
            method_args = tray_command.get('args', [])
            method_kwargs = tray_command.get('kwargs', {})
            if tray_method == 'update': _tray.update(**method_kwargs)
            elif tray_method in {'notification', 'show_message', 'notify'}:
                _tray.show_message(*method_args, **method_kwargs)
            elif tray_method == 'hide': _tray.hide()
            # elif tray_method == 'unhide': _tray.un_hide()
            elif tray_method == 'close':
                _tray.close()
                _tray_item = None


def activate_instance(port):
    r_text = ''
    while port <= 2004 and not r_text:
        with suppress(requests.RequestException):
            endpoint = f'http://127.0.0.1:{port}'
            if args.exit:  # --exit argument
                r_text = requests.post(f'{endpoint}/exit/').text
            elif args.uris:  # MC was supplied at least one path to a folder/file
                data = {'uris': args.uris, 'queue': args.queue, 'play_next': args.playnext}
                r_text = requests.post(f'{endpoint}/play/', data=data).text
            else:  # neither --exit nor paths was supplied
                r_text = requests.post(f'{endpoint}/').text
        port += 1
    return not not r_text


if __name__ == '__main__':
    mp.freeze_support()
    # if the (exact) program is already running, open the running GUI and exit this instance
    #   running a portable version after running an installed version won't open up the second GUI
    try:
        with suppress(FileNotFoundError): os.remove('music_caster.log')
        # if an instance is already running, open that one's GUI and exit this instance
        if is_already_running(threshold=1 if os.path.exists(UNINSTALLER) else 2): raise PermissionError
    except PermissionError:
        # if music_caster.log can't be opened, its being used by an existing Music Caster process
        if IS_FROZEN and not DEBUG:
            activate_instance(2001)
            sys.exit()
    if args.exit: sys.exit()
    tray_process = mp.Process(target=system_tray, args=(daemon_commands, tray_process_queue), daemon=True)
    tray_process.start()


from helpers import *
from audio_player import AudioPlayer
import base64
from contextlib import suppress
from itertools import islice
from collections import defaultdict, deque
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timedelta
import errno
# noinspection PyUnresolvedReferences
import encodings.idna  # DO NOT REMOVE
from functools import cmp_to_key
import glob
import hashlib
import io
import json
import logging
from logging.handlers import RotatingFileHandler
from math import log10
from pathlib import Path
import pprint
from random import shuffle
from shutil import copyfileobj, rmtree
from threading import Thread
from win32com.universal import com_error
import traceback
import urllib.parse
from urllib.parse import urlsplit
import webbrowser  # takes 0.05 seconds
import zipfile
# 3rd party imports
from Cryptodome.Cipher import Blowfish
from flask import Flask, jsonify, render_template, request, redirect, send_file, Response, make_response
from werkzeug.exceptions import InternalServerError
import pychromecast.controllers.media
from pychromecast.error import UnsupportedNamespace, NotConnected
from pychromecast.config import APP_MEDIA_RECEIVER
from pychromecast import Chromecast
import pynput.keyboard
import pypresence
import threading
import pythoncom
from PIL import UnidentifiedImageError
from urllib3.exceptions import ProtocolError
import win32com.client
from win32comext.shell import shell, shellcon
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError

main_window = Sg.Window('')
working_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(working_dir)
WELCOME_MSG = gt('Thanks for installing Music Caster.') + '\n' + \
              gt('Music Caster is running in the tray.')
STREAM_CHUNK = 1024
MUSIC_CASTER_DISCORD_ID = '696092874902863932'
EMAIL = 'elijahllopezz@gmail.com'
AUDIO_EXTS = ('mp3', 'mp4', 'mpeg', 'm4a', 'flac', 'aac', 'ogg', 'opus', 'wma', 'wav')
AUDIO_FILE_TYPES = (('Audio File', '*.' + ' *.'.join(AUDIO_EXTS) + ' *.m3u *.m3u8'),)
SETTINGS_FILE = 'settings.json'
PRESSED_KEYS = set()
settings_file_lock = threading.Lock()
last_play_command = 0  # last call to /play/
settings_last_modified, last_press = 0, time.time() + 5
update_last_checked = time.time()  # check every hour
active_windows = {'main': False}
main_last_event = None
# noinspection PyTypeChecker
cast: Chromecast = None
# playlist_name: [], file_path: metadata, url/string: metadata
playlists, all_tracks, url_metadata = {}, {}, {}
all_tracks_sorted_sort_key = []
tray_playlists, tray_folders = [gt('Playlists Menu')], []
mouse_hover = pl_name = ''
pl_tracks = []  # keep track of paths when editing playlists
CHECK_MARK = '✓'
chromecasts, device_names = [], [f'{CHECK_MARK} ' + gt('Local device')]
music_folders = []
music_queue, done_queue, next_queue = deque(), deque(), deque()
deezer_opened = update_devices = exit_flag = False
playing_url = update_gui_queue = update_volume_slider = False
# live_lag = 0.0
# seconds but using time()
progress_bar_last_update = track_position = timer = track_end = track_length = track_start = 0
DEFAULT_FOLDER = home_music_folder = f'{Path.home()}/Music'.replace('\\', '/')
DEFAULT_THEME = {'accent': '#00bfff', 'background': '#121212', 'text': '#d7d7d7', 'alternate_background': '#222222'}
settings = {  # default settings
    'previous_device': None, 'window_locations': {}, 'update_message': '', 'EXPERIMENTAL': False,
    'auto_update': True, 'run_on_startup': True, 'notifications': True, 'shuffle': False, 'repeat': None,
    'discord_rpc': False, 'save_window_positions': True, 'populate_queue_startup': False, 'persistent_queue': False,
    'volume': 100, 'muted': False, 'volume_delta': 5, 'scrubbing_delta': 5, 'flip_main_window': False,
    'show_track_number': False, 'folder_cover_override': False, 'show_album_art': True, 'folder_context_menu': True,
    'vertical_gui': False, 'mini_mode': False, 'mini_on_top': True, 'scan_folders': True, 'update_check_hours': 1,
    'timer_shut_down': False, 'timer_hibernate': False, 'timer_sleep': False, 'show_queue_index': True,
    'queue_library': False, 'lang': '', 'theme': DEFAULT_THEME.copy(), 'use_last_folder': False,
    'last_folder': DEFAULT_FOLDER, 'track_format': '&artist - &title', 'reversed_play_next': False,
    'music_folders': [DEFAULT_FOLDER], 'playlists': {}, 'queues': {'done': [], 'music': [], 'next': []}}
default_settings = deepcopy(settings)
indexing_tracks_thread = save_queue_thread = Thread()
playing_status = PlayingStatus()
ydl = YoutubeDL(auto_init=False)
sar = SystemAudioRecorder()
app = Flask(__name__)
app.jinja_env.lstrip_blocks = app.jinja_env.trim_blocks = True
logging.getLogger('werkzeug').disabled = not DEBUG
os.environ['WERKZEUG_RUN_MAIN'] = 'true'
os.environ['FLASK_SKIP_DOTENV'] = '1'
stop_discovery = lambda: None  # stop chromecast discovery


def tray_notify(message, title='Music Caster', context=''):
    if message == 'update_available':
        message = gt('Update $VER is available').replace('$VER', f'v{context}')
    # wrapper for tray_process_queue
    tray_process_queue.put({'method': 'notify', 'args': (title, message)})


def save_settings():
    global settings, settings_last_modified
    with settings_file_lock:
        try:
            with open(SETTINGS_FILE, 'w') as outfile:
                json.dump(settings, outfile, indent=4)
            settings_last_modified = os.path.getmtime(SETTINGS_FILE)
        except OSError as _e:
            if _e.errno == errno.ENOSPC:
                tray_notify(gt('ERROR') + ': ' + gt('No space left on device to save settings'))
            else:
                tray_notify(gt('ERROR') + f': {_e}')


def refresh_tray():
    repeat_menu = [gt('Repeat All') + f' {CHECK_MARK}' * (settings['repeat'] is False),
                   gt('Repeat One') + f' {CHECK_MARK}' * (settings['repeat'] is True),
                   gt('Repeat Off') + f' {CHECK_MARK}' * (settings['repeat'] is None)]
    tray_menu_default = ['', [gt('Settings'), gt('Rescan Library'), gt('Refresh Devices'), gt('Select Device'),
                              device_names, gt('Timer'), [gt('Set Timer'), gt('Cancel Timer')], gt('Play'),
                              [gt('System Audio'),
                               gt('URL'), [gt('Play URL'), gt('Queue URL'), gt('Play URL Next')],
                               gt('Folders'), tray_folders, gt('Playlists'), tray_playlists,
                               gt('Select File(s)'),
                               [gt('Play File(s)'), gt('Queue File(s)'), gt('Play File(s) Next')], gt('Play All')],
                              gt('Exit')]]
    tray_menu_playing = ['', [gt('Settings'), gt('Rescan Library'), gt('Refresh Devices'), gt('Select Device'),
                              device_names, gt('Timer'), [gt('Set Timer'), gt('Cancel Timer')], gt('Controls'),
                              [gt('locate track', 1), gt('Repeat Options'), repeat_menu, gt('Stop'),
                               gt('previous track', 1), gt('next track', 1), gt('Pause')], gt('Play'),
                              [gt('System Audio'),
                               gt('URL'), [gt('Play URL'), gt('Queue URL'), gt('Play URL Next')],
                               gt('Folders'), tray_folders, gt('Playlists'), tray_playlists, gt('Select File(s)'),
                               [gt('Play File(s)'), gt('Queue File(s)'), gt('Play File(s) Next')], gt('Play All')],
                              gt('Exit')]]
    tray_menu_paused = ['', [gt('Settings'), gt('Rescan Library'), gt('Refresh Devices'), gt('Select Device'),
                             device_names, gt('Timer'), [gt('Set Timer'), gt('Cancel Timer')], gt('Controls'),
                             [gt('locate track', 1), gt('Repeat Options'), repeat_menu, gt('Stop'),
                              gt('previous track', 1), gt('next track', 1), gt('Resume')], gt('Play'),
                             [gt('System Audio'), gt('URL'),
                              [gt('Play URL'), gt('Queue URL'), gt('Play URL Next')], gt('Folders'), tray_folders,
                              gt('Playlists'), tray_playlists, gt('Select File(s)'),
                              [gt('Play File(s)'), gt('Queue File(s)'), gt('Play File(s) Next')], gt('Play All')],
                             gt('Exit')]]
    tray_folders.clear()
    tray_folders.append(f'{gt("Select Folder(s)")}::PF')
    for folder in settings['music_folders']:
        folder = folder.replace('\\', '/').split('/')
        folder = f'../{"/".join(folder[-2:])}::PF' if len(folder) > 2 else ('/'.join(folder) + '::PF')
        tray_folders.append(folder)
    # refresh playlists
    tray_playlists.clear()
    tray_playlists.append(gt('Playlists Menu'))
    tray_playlists.extend([f'{pl}::PL'.replace('&', '&&&') for pl in settings['playlists'].keys()])
    # tell tray process to update
    icon = FILLED_ICON if playing_status.playing() else UNFILLED_ICON
    if playing_status.busy():
        menu = tray_menu_playing if playing_status.playing() else tray_menu_paused
        metadata = get_current_metadata()
        title, artists = metadata['artist'], metadata['title']
        _tooltip = f"{get_first_artist(artists)} - {title}".replace('&', '&&&')
    else:
        menu, _tooltip = tray_menu_default, 'Music Caster'
    if settings.get('DEBUG', DEBUG): _tooltip += ' [DEBUG]'
    tray_process_queue.put({'method': 'update', 'kwargs': {'menu': menu, 'data_base64': icon, 'tooltip': _tooltip}})


def change_settings(settings_key, new_value):
    """ can be called from non-main thread """
    global settings, active_windows
    if settings[settings_key] != new_value:
        settings[settings_key] = new_value
        save_settings()
        if settings_key == 'repeat':
            refresh_tray()
            if settings['notifications']:
                msg = {None: lambda: gt('Repeat set to Off'),
                       True: lambda: gt('Repeat set to One'),
                       False: lambda: gt('Repeat set to All')}[new_value]()
                tray_notify(msg)
    return new_value


def save_queues():
    global save_queue_thread

    def _save_queue():
        settings['queues']['done'] = tuple(done_queue)
        settings['queues']['music'] = tuple(music_queue)
        settings['queues']['next'] = tuple(next_queue)
        save_settings()

    if settings['persistent_queue'] and not save_queue_thread.is_alive():
        save_queue_thread = Thread(target=_save_queue, name='SaveQueue')
        save_queue_thread.start()


def update_volume(new_vol):
    """new_vol: float[0, 100]"""
    if active_windows['main']: main_window['volume_slider'].update(value=new_vol)
    new_vol = new_vol / 100
    audio_player.set_volume(new_vol)
    if cast is not None:
        with suppress(NotConnected): cast.set_volume(new_vol)


def update_repeat_button():
    """ updates repeat button of main window """
    repeat_button: Sg.Button = main_window['repeat']
    repeat_img, new_tooltip = repeat_img_tooltip(settings['repeat'])
    repeat_button.metadata = settings['repeat']
    repeat_button.update(image_data=repeat_img)
    repeat_button.set_tooltip(new_tooltip)


def cycle_repeat(update_main=False):
    """
    :param update_main: Only set to True on main Thread
    :return: new repeat value
    """
    # Repeat Off (None) becomes All (False) becomes One (True) becomes Off
    new_repeat_setting = {None: False, True: None, False: True}[settings['repeat']]
    if update_main and active_windows['main']: update_repeat_button()  # update main window if it is active
    return change_settings('repeat', new_repeat_setting)


def create_email_url():
    try:
        with open('music_caster.log') as f:
            log_lines = f.read().splitlines()[-10:]  # get last 10 lines of the log
    except FileNotFoundError:
        log_lines = []
    log_lines = '%0D%0A'.join(log_lines)
    email_body = f'body=%0D%0A%23%20Last%20Few%20Lines%20of%20the%20Log%0D%0A%0D%0A{log_lines}'
    mail_to = f'mailto:{EMAIL}?subject=Regarding%20Music%20Caster%20v{VERSION}&{email_body}'
    return mail_to


def handle_exception(exception, restart_program=False):
    current_time = str(datetime.now())
    trace_back_msg = traceback.format_exc()
    exc_type, exc_tb = sys.exc_info()[0], sys.exc_info()[2]
    if playing_url: playing_uri = 'url'
    elif sar.alive: playing_uri = 'system audio'
    elif playing_status.busy(): playing_uri = 'file'
    else: playing_uri = 'N/A'
    try:
        with open('music_caster.log') as f:
            log_lines = f.read().splitlines()[-5:]  # get last 5 lines of the log
    except FileNotFoundError:
        log_lines = []
    payload = {'VERSION': VERSION, 'EXCEPTION TYPE': exc_type.__name__, 'LINE': exc_tb.tb_lineno,
               'PORTABLE': not os.path.exists(UNINSTALLER),
               'MQ': len(music_queue), 'NQ': len(next_queue), 'DQ': len(done_queue),
               'TRACEBACK': fix_path(trace_back_msg), 'MAC': hashlib.md5(get_mac().encode()).hexdigest(),
               'FATAL': restart_program, 'LOG': log_lines, 'CASTING': cast is not None,
               'OS': platform.platform(), 'TIME': current_time, 'PLAYING_TYPE': playing_uri}
    if IS_FROZEN:
        with suppress(requests.RequestException):
            requests.post('https://dc19f29a6822522162e00f0b4bee7632.m.pipedream.net', json=payload)
    try:
        with open('error.log', 'r') as _f:
            content = _f.read()
    except (FileNotFoundError, ValueError):
        content = ''
    with open('error.log', 'w') as _f:
        _f.write(pprint.pformat(payload))
        _f.write('\n')
        _f.write(content)
    if restart_program:
        with suppress(Exception): stop('error handling')
        tray_notify(gt('An error occurred, restarting now'))
        time.sleep(2)
        tray_process_queue.put({'method': 'close'})
        if IS_FROZEN: os.startfile('Music Caster.exe')
        else: raise exception  # raise exception if running in script rather than executable
        sys.exit()


def get_album_art(file_path: str) -> tuple:  # mime: str, data: str / (None, None)
    with suppress(MutagenError):
        folder = os.path.dirname(file_path)
        if settings['folder_cover_override']:
            for ext in ('png', 'jpg', 'jpeg'):
                folder_cover = os.path.join(folder, f'cover.{ext}')
                if os.path.exists(folder_cover):
                    with open(folder_cover, 'rb') as f:
                        data = base64.b64encode(f.read())
                    return ext, data
        tags = mutagen.File(file_path)
        if tags is not None:
            for tag in tags.keys():
                if 'APIC' in tag:
                    return tags[tag].mime, base64.b64encode(tags[tag].data).decode()
    return None, None


def get_current_album_art():
    if sar.alive: return custom_art('SYS')
    art = None
    if playing_status.busy() and music_queue:
        uri = music_queue[0]
        if uri.startswith('http'):
            try:
                # use 'art_data' else download 'art' link and cache to 'art_data'
                if 'art_data' in url_metadata[uri]: return url_metadata[uri]['art_data']
                art_src = url_metadata[uri]['art']  # 'art' is a key to a value of a link
                url_metadata[uri]['art_data'] = art_data = base64.b64encode(requests.get(art_src).content)
                return art_data
            except KeyError:
                return custom_art('URL')
        with suppress(MutagenError):
            art = get_album_art(uri)[1]  # get_album_art(uri)[1] can be None
    return DEFAULT_ART if art is None else art


def get_metadata_wrapped(file_path: str) -> dict:  # keys: title, artist, album, sort_key
    try:
        return get_metadata(file_path)
    except mutagen.MutagenError:
        try:
            file_path = file_path.replace('\\', '/')
            metadata = all_tracks[file_path]
            return metadata
        except KeyError:
            return {'title': Unknown('Title'), 'artist': Unknown('Artist'),
                    'album': Unknown('Title'), 'sort_key': get_file_name(file_path)}


def get_uri_metadata(uri, read_file=True):
    """
    get metadata from all_track and resort to url_metadata if not found in all_tracks
      if file/url is not in all_track. e.g. links
    if read_file is False, raise a KeyError instead of reading metadata from file.
    """
    uri = uri.replace('\\', '/')
    try:
        return all_tracks[uri]
    except KeyError:
        try:
            # if uri is a url
            return url_metadata[uri]
        except KeyError:
            # uri is probably a file that has not been cached yet
            if not read_file: raise KeyError
            metadata = get_metadata_wrapped(uri)
            if uri.startswith('http'): return metadata
            all_tracks[uri] = metadata
            return metadata


def get_current_metadata() -> dict:
    if sar.alive: return url_metadata['SYSTEM_AUDIO']
    if music_queue and playing_status.busy(): return get_uri_metadata(music_queue[0])
    return {'artist': '', 'title': gt('Nothing Playing'), 'album': ''}


def get_audio_uris(uris: Iterable, scan_uris=True, ignore_m3u=False, parsed_m3us=None):
    """
    :param uris: A list of URIs (urls, folders, m3u files, files)
    :param scan_uris: whether to add to uris_to_scan
    :param ignore_m3u: whether to ignore .m3u(8) files
    :param parsed_m3us: m3u files that have already been parsed. This is to avoid recursive parsing
    :return: generator of valid audio files
    """
    if parsed_m3us is None: parsed_m3us = set()
    if isinstance(uris, str): uris = (uris,)
    for uri in uris:
        if uri in playlists:
            yield from get_audio_uris(playlists[uri], scan_uris=scan_uris, ignore_m3u=ignore_m3u,
                                      parsed_m3us=parsed_m3us)
        elif os.path.isdir(uri):  # if scanning a folder, ignore playlist files as they aren't audio files
            yield from get_audio_uris(glob.iglob(f'{glob.escape(uri)}/**/*.*', recursive=True),
                                      scan_uris=scan_uris, ignore_m3u=True, parsed_m3us=parsed_m3us)
        elif os.path.isfile(uri):
            uri = uri.replace('\\', '/')
            if not ignore_m3u and (uri.endswith('.m3u') or uri.endswith('.m3u8')) and uri not in parsed_m3us:
                parsed_m3us.add(uri)
                yield from get_audio_uris(parse_m3u(uri), parsed_m3us=parsed_m3us)
            elif valid_audio_file(uri):
                if scan_uris and uri not in all_tracks: uris_to_scan.put(uri)
                yield uri
        elif uri.startswith('http'):
            if scan_uris and uri not in url_metadata: uris_to_scan.put(uri)
            yield uri


def index_all_tracks(update_global=True, ignore_files: set = None):
    """
    returns the music library dict if update_global is False
    starts scanning and building the music library/database if update_global is True
    ignore_files is a list (converted to set) of files to not include in the return value / scan
        usually used with update_global=False (think about it)
    """
    global indexing_tracks_thread, all_tracks
    # make sure ignore_files is a set
    try: ignore_files = set(ignore_files)
    except TypeError: ignore_files = set()

    def _index_library():
        global all_tracks, update_gui_queue, all_tracks_sorted_sort_key
        """
        Scans folders provided in settings and adds them to a dictionary
        Does not ignore the files that in ignore_files by design
        """
        use_temp = len(all_tracks)  # use temp if all_tracks is not empty
        all_tracks_temp = {}
        dict_to_use = all_tracks_temp if use_temp else all_tracks
        for uri in get_audio_uris(settings['music_folders'], False, True):
            dict_to_use[uri] = get_metadata_wrapped(uri)
        if use_temp: all_tracks = all_tracks_temp.copy()
        update_gui_queue = True
        # scan playlist items
        for _ in get_audio_uris(playlists.keys()): pass
        all_tracks_sorted_sort_key = sorted(all_tracks.items(), key=lambda item: item[1]['sort_key'])

    if not update_global:
        temp_tracks = all_tracks.copy()
        for ignore_file in ignore_files: temp_tracks.pop(ignore_file, None)
        return temp_tracks
    if indexing_tracks_thread is None:
        indexing_tracks_thread = Thread(target=_index_library, daemon=True, name='IndexLibrary')
        indexing_tracks_thread.start()
    elif not indexing_tracks_thread.is_alive():  # force reindex
        indexing_tracks_thread = Thread(target=_index_library, daemon=True, name='IndexLibrary')
        indexing_tracks_thread.start()


def download(url, outfile):
    # throws ConnectionAbortedError
    r = requests.get(url, stream=True)
    if outfile.endswith('.zip'):
        outfile = outfile.replace('.zip', '')
        z = zipfile.ZipFile(io.BytesIO(r.content))
        z.extractall(outfile)
    else:
        with open(outfile, 'wb') as _f:
            copyfileobj(r.raw, _f)


def set_save_position_callback(window: Sg.Window, _key):
    def save_window_position(event):
        if event.widget is window.TKroot:
            settings['window_locations'][_key] = window.CurrentLocation()
            save_settings()

    window.TKroot.bind('<Destroy>', save_window_position)


def get_window_location(window_key):
    if not settings['save_window_positions']: window_key = 'DEFAULT'
    return settings['window_locations'].get(window_key, (None, None))


def load_settings(first_load=False):  # up to 0.4 seconds
    """
    load (and fix if needed) the settings file
    calls refresh_tray(), index_all_tracks(), save_setting()
    """
    global settings, playlists, music_folders, settings_last_modified, DEFAULT_FOLDER
    _save_settings = False
    with settings_file_lock:
        try:
            with open(SETTINGS_FILE) as json_file:
                loaded_settings = json.load(json_file)
        except (FileNotFoundError, json.JSONDecodeError):
            # if file does not exist
            loaded_settings = {}
        for setting_name, setting_value in tuple(loaded_settings.items()):
            loaded_settings[setting_name.replace(' ', '_')] = loaded_settings.pop(setting_name)
        for setting_name, setting_value in settings.items():
            does_not_exist = setting_name not in loaded_settings
            # use default settings if key/value does not exist
            if does_not_exist and setting_name in default_settings:
                loaded_settings[setting_name] = setting_value
                _save_settings = True
            elif setting_name in {'theme', 'queues'}:
                # for theme key
                for k, v in setting_value.items():
                    if k not in loaded_settings[setting_name]:
                        loaded_settings[setting_name][k] = v
                        _save_settings = True
        settings = loaded_settings
        # sort playlists by name
        playlists = settings['playlists'] = {k: settings['playlists'][k] for k in sorted(settings['playlists'].keys())}
        # if music folders were modified, re-index library
        if music_folders != settings['music_folders'] or first_load:
            music_folders = settings['music_folders']
            if settings['scan_folders']: index_all_tracks()
        refresh_tray()
        DEFAULT_FOLDER = music_folders[0] if music_folders else home_music_folder
        theme = settings['theme']
        for k, v in theme.copy().items():
            # validate settings file color codes
            if not valid_color_code(v):
                _save_settings = True
                theme[k] = DEFAULT_THEME[k]
        Shared.lang = settings['lang']
        Shared.track_format = settings['track_format']
        fg, bg, accent = theme['text'], theme['background'], theme['accent']
        Sg.set_options(text_color=fg, element_text_color=fg, input_text_color=fg,
                       button_color=(bg, accent), element_background_color=bg, scrollbar_color=bg,
                       text_element_background_color=bg, background_color=bg,
                       input_elements_background_color=bg, progress_meter_color=accent,
                       border_width=0, slider_border_width=1, progress_meter_border_depth=0, font=FONT_NORMAL)
    if _save_settings: save_settings()
    settings_last_modified = os.path.getmtime(SETTINGS_FILE)


@app.errorhandler(404)
def page_not_found(_):
    return redirect('/')


@app.route('/', methods=['GET', 'POST'])
def web_index():  # web GUI
    if request.method == 'POST':
        daemon_commands.put('__ACTIVATED__')  # tells main loop to bring to front all GUI's
        return 'true' if any(active_windows.values()) else 'Music Caster'
    if request.args:
        api_msg = 'Invalid Command'
        if 'play' in request.args:
            if resume():
                api_msg = 'resumed playback'
            else:
                if music_queue:
                    play(music_queue[0])
                    api_msg = 'started playing first track in queue'
                else:
                    play_all()
                    api_msg = 'shuffled all and started playing'
        elif 'pause' in request.args:
            pause()  # resume == play
            api_msg = 'pause called'
        elif 'next' in request.args:
            next_track(times=int(request.args.get('times', 1)), forced=True)
            api_msg = 'next track called'
        elif 'prev' in request.args:
            prev_track(times=int(request.args.get('times', 1)), forced=True)
            api_msg = 'prev track called'
        elif 'repeat' in request.args:
            cycle_repeat()
            api_msg = 'cycled repeat to ' + {None: 'off', True: 'one', False: 'all'}[settings['repeat']]
        elif 'shuffle' in request.args:
            shuffle_option = change_settings('shuffle', not settings['shuffle'])
            api_msg = f'shuffle set to {shuffle_option}'
            if shuffle_option: shuffle_queue()
            else: un_shuffle_queue()
        if 'is_api' in request.args:
            return api_msg
        return redirect('/')
    metadata = get_current_metadata()
    art = get_current_album_art()
    if type(art) == bytes: art = art.decode()
    art = f'data:image/png;base64,{art}'
    repeat_option = settings['repeat']
    repeat_color = 'red' if settings['repeat'] is not None else ''
    shuffle_option = 'red' if settings['shuffle'] else ''
    # sort by the formatted title
    list_of_tracks = []
    if all_tracks_sorted_sort_key:
        sorted_tracks = all_tracks_sorted_sort_key
    else:
        sorted_tracks = sorted(all_tracks.items(), key=lambda item: item[1]['sort_key'])
    for filename, data in sorted_tracks:
        href = '/play?' + urllib.parse.urlencode({'uri': filename})
        src_href = '/file?' + urllib.parse.urlencode({'path': filename})
        list_of_tracks.append({'text': format_uri(filename), 'title': filename, 'src': src_href, 'href': href})
    _queue = create_track_list()
    device_index = 0
    for i, device_name in enumerate(device_names):
        if device_name.startswith(CHECK_MARK):
            device_index = i
            break
    formatted_devices = ['Local Device'] + [cc.name for cc in chromecasts]
    return render_template('index.html', device_name=platform.node(), shuffle=shuffle_option, repeat_color=repeat_color,
                           playing_status=playing_status, metadata=metadata, art=art,
                           settings=settings, list_of_tracks=list_of_tracks, repeat_option=repeat_option, queue=_queue,
                           playing_index=len(done_queue), device_index=device_index, devices=formatted_devices,
                           version=VERSION, gt=gt)


@app.route('/play/', methods=['GET', 'POST'])
def api_play():
    global last_play_command
    from_explorer = time.time() - last_play_command < 0.5
    queue_only = request.values.get('queue', 'false').lower() == 'true' or from_explorer
    play_next = request.values.get('play_next', 'false').lower() == 'true'
    # < 0.5 because that's how fast Windows would open each instance of MC
    last_play_command = time.time()
    if 'uris' in request.values:
        play_uris(request.values.getlist('uris'), queue_uris=queue_only, play_next=play_next,
                  from_explorer=from_explorer)
    elif 'uri' in request.values:
        play_uris([request.values['uri']], queue_uris=queue_only, play_next=play_next, from_explorer=from_explorer)
        # Since its the web GUI, we can queue all as well
        already_queueing = False
        for thread in threading.enumerate():
            if thread.name in {'QueueAll', 'PlayAll'} and thread.is_alive():
                already_queueing = True
                break
        if not already_queueing: Thread(target=queue_all, name='QueueAll', daemon=True).start()
    return redirect('/') if request.method == 'GET' else 'true'


@app.route('/state/')
def api_state():
    metadata = get_current_metadata()
    now_playing = {'status': str(playing_status), 'volume': settings['volume'], 'lang': settings['lang'],
                   'title': str(metadata['title']), 'artist': str(metadata['artist']), 'album': str(metadata['album']),
                   'queue_length': len(done_queue) + len(music_queue) + len(next_queue)}
    return jsonify(now_playing)


@app.errorhandler(InternalServerError)
def handle_500(_e):
    original = getattr(_e, "original_exception", None)

    if original is None:
        # direct 500 error, such as abort(500)
        handle_exception(_e)
        return gt('An Internal Server Error occurred') + f': {_e}'

    # wrapped unhandled error
    handle_exception(original)
    return gt('An Internal Server Error occurred') + f': {original}'


@app.route('/debug/')
def api_get_debug_info():
    if settings.get('DEBUG', DEBUG):
        return jsonify({'pressed_keys': list(PRESSED_KEYS),
                        'last_press': datetime.fromtimestamp(last_press),
                        'last_traceback': sys.exc_info(),
                        'mac': get_mac()})
    return gt('set DEBUG = true in `settings.json` to enable this page')


@app.route('/running/', methods=['GET', 'POST', 'OPTIONS'])
def api_running():
    response = make_response('true')
    if request.environ.get('HTTP_ORIGIN') in {'https://elijahlopez.herokuapp.com', 'http://elijahlopez.herokuapp.com'}:
        response.headers.add('Access-Control-Allow-Origin', request.environ['HTTP_ORIGIN'])
    return response


@app.route('/exit/', methods=['GET', 'POST'])
def api_exit():
    daemon_commands.put(gt('Exit'))
    return 'true'


@app.route('/change-setting/', methods=['POST'])
def api_change_setting():
    with suppress(KeyError):
        setting_key = request.json['setting_name']
        if setting_key in settings or setting_key in {'timer_stop'}:
            val = request.json['value']
            change_settings(setting_key, val)
            timer_settings = {'timer_hibernate', 'timer_sleep',
                              'timer_shut_down', 'timer_stop'}
            if val and setting_key in timer_settings:
                for timer_setting in timer_settings.difference({setting_key, 'timer_stop'}):
                    change_settings(timer_setting, False)
            if setting_key == 'volume':
                update_volume(0 if settings['muted'] else settings['volume'])
        return 'true'
    return 'false'


@app.route('/refresh-devices/')
def api_refresh_devices():
    start_chromecast_discovery(start_thread=True)
    return 'true'


@app.route('/rescan-library/')
def api_rescan_library():
    index_all_tracks()
    return 'true'


@app.route('/change-device/', methods=['POST'])
def api_change_device():
    with suppress(KeyError):
        change_device(int(request.json['device_index']))
        return 'true'
    return 'false'


@app.route('/timer/', methods=['GET', 'POST'])
def api_set_timer():
    global timer
    if request.method == 'POST':
        val = request.data.decode()
        val = val.lower()
        if val == 'cancel':
            cancel_timer()
        else:
            val = int(val)
            timer = val + time.time()
            timer_set_to = datetime.now() + timedelta(minutes=val // 60)
            if platform.system() == 'Windows':
                timer_set_to = timer_set_to.strftime('%#I:%M %p')
            else:
                timer_set_to = timer_set_to.strftime('%-I:%M %p')  # Linux
            return timer_set_to
        return 'timer cancelled'
    else:  # GET request
        return str(timer)


@app.route('/file/')
def api_get_file():
    if 'path' in request.args:
        file_path = request.args['path']
        if os.path.isfile(file_path) and valid_audio_file(file_path) or file_path == 'DEFAULT_ART':
            if request.args.get('thumbnail_only', False) or file_path == 'DEFAULT_ART':
                mime_type, img_data = get_album_art(file_path)
                if mime_type is None:
                    mime_type, img_data = 'image/png', DEFAULT_ART
                else:
                    img_data = base64.b64decode(img_data)
                try:
                    ext = mime_type.split('/')[1]
                except IndexError:
                    ext = 'png'
                return send_file(io.BytesIO(img_data), attachment_filename=f'cover.{ext}',
                                 mimetype=mime_type, as_attachment=True, cache_timeout=360000, conditional=True)
            return send_file(file_path, conditional=True, as_attachment=True, cache_timeout=360000)
    return '400'


@app.route('/dz/')
def api_get_dz():
    if 'url' in request.args:
        # TODO: cache content to prevent extra requests
        url = request.args['url']
        metadata = url_metadata[url]
        file_url = metadata['file_url']
        range_header = {'Range': request.headers.get('Range', 'bytes=0-')}
        r = requests.get(file_url, headers=range_header, stream=True)
        start_bytes = int(range_header['Range'].split('=', 1)[1].split('-', 1)[0])
        # noinspection PyProtectedMember
        blowfish_key = metadata['bf_key']
        iv = b'\x00\x01\x02\x03\x04\x05\x06\x07'

        def generate():
            nonlocal start_bytes
            # if start_bytes is not a multiple of 2048, first yield will be < 2048 to fix the chunks
            extra_bytes = start_bytes % 2048
            if extra_bytes != 0:
                extra_bytes = 2048 - extra_bytes
                chunk = next(r.iter_content(extra_bytes))
                if start_bytes // 2048 == 0:
                    chunk = Blowfish.new(blowfish_key, Blowfish.MODE_CBC, iv).decrypt(chunk)
                yield chunk
                start_bytes += extra_bytes
            for i, chunk in enumerate(r.iter_content(2048), start_bytes // 2048):
                if (i % 3) == 0 and len(chunk) == 2048:
                    chunk = Blowfish.new(blowfish_key, Blowfish.MODE_CBC, iv).decrypt(chunk)
                yield chunk

        content_type = r.headers['Content-Type']
        rv = Response(generate(), 206, mimetype=content_type, content_type=content_type)
        rv.headers['Content-Range'] = r.headers['Content-Range']
        return rv
    return '400'


@app.route('/system-audio/')
@app.route('/system-audio/<get_thumb>')
def api_system_audio(get_thumb=''):
    """
    send system audio to chromecast
    """
    if get_thumb:
        return send_file(io.BytesIO(base64.b64decode(custom_art('SYS'))), attachment_filename=f'thumbnail.png',
                         mimetype='image/png', as_attachment=True, cache_timeout=360000, conditional=True)
    return Response(sar.get_audio_data())


@cmp_to_key
def chromecast_sorter(cc1: Chromecast, cc2: Chromecast):
    # sort by groups, then by name, then by UUID
    if cc1.device.cast_type == 'group' and cc2.device.cast_type != 'group': return -1
    if cc1.device.cast_type != 'group' and cc2.device.cast_type == 'group': return 1
    if cc1.name < cc2.name: return -1
    if cc1.name > cc2.name: return 1
    if str(cc1.uuid) > str(cc2.uuid): return 1
    return -1


def chromecast_callback(chromecast):
    global update_devices, cast, chromecasts
    previous_device = settings['previous_device']
    if str(chromecast.uuid) == previous_device and cast != chromecast:
        cast = chromecast
        cast.wait()
    if chromecast.uuid not in [_cc.uuid for _cc in chromecasts]:
        chromecasts.append(chromecast)
        # chromecasts.sort(key=lambda _cc: (_cc.device.model_name, type, _cc.name, _cc.uuid))
        chromecasts.sort(key=chromecast_sorter)
        device_names.clear()
        for _i, _cc in enumerate(['Local device'] + chromecasts):
            _cc: Chromecast
            device_name = _cc if _i == 0 else _cc.name
            if (previous_device is None and _i == 0) or (type(_cc) != str and str(_cc.uuid) == previous_device):
                device_names.append(f'{CHECK_MARK} {device_name}::device')
            else:
                device_names.append(f'    {device_name}::device')
        refresh_tray()


def start_chromecast_discovery(start_thread=False):
    global stop_discovery
    if start_thread: return Thread(target=start_chromecast_discovery, daemon=True, name='CCDiscovery').start()
    # stop any active scanning
    if stop_discovery is not None: stop_discovery()
    chromecasts.clear()
    stop_discovery = pychromecast.get_chromecasts(blocking=False, callback=chromecast_callback)
    time.sleep(WAIT_TIMEOUT + 1)
    stop_discovery()
    stop_discovery = None
    if not device_names:
        device_names.append(f'{CHECK_MARK} Local device')
        refresh_tray()


def change_device(new_idx):
    # new_idx is the index of the new device
    global cast
    new_device: Chromecast = None if (new_idx == 0 or new_idx > len(chromecasts)) else chromecasts[new_idx - 1]

    if cast != new_device:
        device_names.clear()
        for idx, cc in enumerate(['Local device'] + chromecasts):
            cc: Chromecast = cc if idx == 0 else cc.name
            tray_device_name = f'{CHECK_MARK} {cc}::device' if idx == new_idx else f'    {cc}::device'
            device_names.append(tray_device_name)
        refresh_tray()

        current_pos = 0
        if cast is not None and cast.app_id == APP_MEDIA_RECEIVER:
            if playing_status.busy():
                mc = cast.media_controller
                with suppress(UnsupportedNamespace):
                    mc.update_status()  # Switch device without playback loss
                    current_pos = mc.status.adjusted_current_time
                    if mc.is_playing or mc.is_paused: mc.stop()
            with suppress(NotConnected):
                cast.quit_app()
        elif cast is None and audio_player.is_busy():
            current_pos = audio_player.stop()
        cast = new_device
        change_settings('previous_device', None if cast is None else str(cast.uuid))
        if playing_status.busy() and (music_queue or sar.alive):
            if not sar.alive:
                play(music_queue[0], position=current_pos, autoplay=playing_status.playing(), switching_device=True)
            elif not play_system_audio(True):
                playing_status.stop()
        else:
            if cast is not None: cast.wait(timeout=WAIT_TIMEOUT)
            volume = 0 if settings['muted'] else settings['volume']
            update_volume(volume)


def un_shuffle_queue():
    """
    To be called when shuffle is toggled off
        sorts files by natural key...
        splits at current playing
    Does not affect next_queue
    Keeps currently playing the same
    """
    global music_queue, done_queue, update_gui_queue
    if music_queue:
        # keep current playing track the same
        track = music_queue[0]
        temp_list = list(music_queue) + list(done_queue)
        temp_list.sort(key=natural_key_file)
        split_queue_at = temp_list.index(track)
        done_queue = deque(temp_list[:split_queue_at])
        music_queue = deque(temp_list[split_queue_at:])
    elif done_queue:
        # sort and set queue to first item
        music_queue = deque(sorted(done_queue, key=natural_key_file))
        done_queue.clear()
    update_gui_queue = True


def shuffle_queue():
    """
    To be called when shuffle is toggled  on
        extends the music_queue with done_queue
        and then shuffles it
    Does not affect next_queue
    Keeps currently playing the same
    """
    global update_gui_queue, music_queue
    # keep track the same if in the process of playing something
    first_index = 1 if playing_status.busy() and music_queue else 0
    music_queue.extend(done_queue)
    done_queue.clear()
    # shuffle is slow for a deque so use a list
    temp_list = list(music_queue)
    better_shuffle(temp_list, first=first_index)
    music_queue = deque(temp_list)
    update_gui_queue = True


def format_uri(uri: str, use_basename=False):
    try:
        if use_basename: raise TypeError
        metadata = get_uri_metadata(uri, read_file=False)
        title, artist = metadata['title'], metadata['artist']
        if artist == Unknown('Artist') or title == Unknown('Title'): raise KeyError
        formatted = settings['track_format'].replace('&artist', artist).replace('&title', title)
        number = metadata.get('track_number', '')
        if '&trck' in formatted:
            formatted = formatted.replace('&trck', number)
        elif settings['show_track_number'] and number:
            formatted = f'[{number}] {formatted}'
        return formatted
    except (TypeError, KeyError):
        if uri.startswith('http'): return uri
        base = os.path.basename(uri)
        return os.path.splitext(base)[0]


def create_track_list():
    """:returns the formatted tracks queue, and the selected value (currently playing)"""
    try:
        max_digits = int(log10(max(len(music_queue) - 1 + len(next_queue), len(done_queue) * 10))) + 2
    except ValueError:
        max_digits = 0
    i = -len(done_queue)
    tracks = []
    # format: Index | Artists - Title
    for items in (done_queue, islice(music_queue, 0, 1), next_queue, islice(music_queue, 1, None)):
        for uri in items:
            formatted_track = format_uri(uri)
            if settings['show_queue_index']:
                if i < 0: pre = f'\u2012{abs(i)} '.center(max_digits, '\u2000')
                else: pre = f'{i} '.center(max_digits, '\u2000')
                formatted_track = f'\u2004{pre}|\u2000{formatted_track}'
                i += 1
            tracks.append(formatted_track)
    return tracks


def after_play(title, artists: str, autoplay, switching_device):
    global cast_last_checked, update_gui_queue
    app_log.info(f'after_play: autoplay={autoplay}, switching_device={switching_device}')
    # prevent Windows from going to sleep
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    if autoplay:
        if settings['notifications'] and not switching_device and not active_windows['main']:
            # artists is comma separated string
            tray_notify(gt('Playing') + f': {get_first_artist(artists)} - {title}')
    playing_status.play()
    refresh_tray()
    cast_last_checked = time.time()
    save_queues()
    if settings['discord_rpc']:
        with suppress(Exception):
            rich_presence.update(state=gt('By') + f': {artists}', details=title, large_image='default',
                                 large_text=gt('Listening'), small_image='logo', small_text='Music Caster')
    update_gui_queue = True


def play_system_audio(switching_device=False):
    global track_position, track_start, track_end, track_length
    if cast is None:
        tray_notify(gt('ERROR') + ': ' + gt('Not connected to a cast device'))
        sar.alive = False
        return False
    else:
        cast.wait(timeout=WAIT_TIMEOUT)
        try:
            cast.set_volume(0 if settings['muted'] else settings['volume'] / 100)
            mc = cast.media_controller
            if mc.status.player_is_playing or mc.status.player_is_paused:
                mc.stop()
                mc.block_until_active(WAIT_TIMEOUT)
            title = 'System Audio'
            artist = platform.node()
            album = 'Music Caster'
            metadata = {'metadataType': 3, 'albumName': album, 'title': title, 'artist': artist}
            url_metadata['SYSTEM_AUDIO'] = {'artist': artist, 'title': title, 'album': album}
            sar.start()  # start recording system audio BEFORE the first request for data
            url = f'http://{get_ipv4()}:{Shared.PORT}/system-audio/'
            mc.play_media(url, 'audio/wav', metadata=metadata, thumb=f'{url}/thumb', stream_type='LIVE')
            mc.block_until_active(WAIT_TIMEOUT)
            start_time = time.time()
            while not mc.status.player_is_playing: time.sleep(0.01)
            mc.play()
            sar.lag = time.time() - start_time  # ~1 second
            track_length = 60 * 60 * 3  # 3 hour default
            track_position = 0
            track_start = time.time() - track_position
            track_end = track_start = track_length
            after_play(title, artist, True, switching_device)
            return True
        except NotConnected:
            tray_notify(gt('ERROR') + ': ' + gt('Could not connect to cast device'))
            return False


# noinspection PyTypeChecker
def get_url_metadata(url, fetch_art=True) -> list:
    """
    Tries to parse url and set url_metadata[url] to parsed metadata
    Supports: YouTube, Soundcloud, any url ending with a valid audio extension
    """
    global deezer_opened
    metadata_list = []
    if url in url_metadata and not url_metadata[url].get('expired', lambda: True)(): return [url_metadata[url]]
    if url.startswith('http') and valid_audio_file(url):  # source url e.g. http://...radio.mp3
        ext = url[::-1].split('.', 1)[0][::-1]
        url_frags = urlsplit(url)
        title, artist, album = url_frags.path.split('/')[-1], url_frags.netloc, url_frags.path[1:]
        url_metadata[url] = metadata = {'title': title, 'artist': artist, 'length': 108000, 'album': album,
                                        'src': url, 'url': url, 'ext': ext, 'expired': lambda: False}
        metadata_list.append(metadata)
    elif 'soundcloud.com' in url:
        with suppress(StopIteration, DownloadError, KeyError):
            r = ydl.extract_info(url, download=False)
            if 'entries' in r:
                for entry in r['entries']:
                    parsed_url = parse_qs(urlparse(entry['url']).query)['Policy'][0].replace('_', '=')
                    policy = base64.b64decode(parsed_url).decode()
                    expiry_time = json.loads(policy)['Statement'][0]['Condition']['DateLessThan']['AWS:EpochTime']
                    album = entry.get('album', r.get('title', 'SoundCloud'))
                    metadata = {'title': entry['title'], 'artist': entry['uploader'], 'album': album,
                                'length': entry['duration'], 'art': entry['thumbnail'], 'src': entry['webpage_url'],
                                'url': entry['url'], 'ext': entry['ext'], 'expired': lambda: time.time() > expiry_time}
                    url_metadata[entry['webpage_url']] = metadata
                    metadata_list.append(metadata)
            else:
                policy = base64.b64decode(parse_qs(urlparse(r['url']).query)['Policy'][0].replace('_', '=')).decode()
                expiry_time = json.loads(policy)['Statement'][0]['Condition']['DateLessThan']['AWS:EpochTime']
                is_expired = lambda: time.time() > expiry_time
                url_metadata[url] = metadata = {'title': r['title'], 'artist': r['uploader'], 'album': 'SoundCloud',
                                                'src': url, 'ext': r['ext'], 'expired': is_expired,
                                                'length': r['duration'], 'art': r['thumbnail'], 'url': r['url']}
                metadata_list.append(metadata)
    elif get_yt_id(url) is not None or url.startswith('ytsearch:'):
        with suppress(StopIteration, DownloadError, KeyError):
            r = ydl.extract_info(url, download=False)
            if 'entries' in r:
                for entry in r['entries']:
                    audio_url = max(entry['formats'], key=lambda item: item['tbr'] * (item['vcodec'] == 'none'))['url']
                    formats = [_f for _f in entry['formats'] if _f['acodec'] != 'none' and _f['vcodec'] != 'none']
                    formats.sort(key=lambda _f: _f['width'])
                    _f = formats[0]
                    expiry_time = int(parse_qs(urlparse(_f['url']).query)['expire'][0])
                    album = entry.get('album', r.get('title', entry.get('playlist', 'YouTube')))
                    metadata = {'title': entry['title'], 'artist': entry['uploader'], 'art': entry['thumbnail'],
                                'album': album, 'length': entry['duration'], 'ext': _f['ext'],
                                'expired': lambda: time.time() > expiry_time,
                                'src': entry['webpage_url'], 'url': _f['url'], 'audio_url': audio_url}
                    for webpage_url in get_yt_urls(entry['id']): url_metadata[webpage_url] = metadata
                    metadata_list.append(metadata)
            else:
                audio_url = max(r['formats'], key=lambda item: item['tbr'] * (item['vcodec'] == 'none'))['url']
                formats = [_f for _f in r['formats'] if _f['acodec'] != 'none' and _f['vcodec'] != 'none']
                formats.sort(key=lambda _f: _f['width'])
                _f = formats[0]
                expiry_time = int(parse_qs(urlparse(_f['url']).query)['expire'][0])
                metadata = {'title': r.get('track', r['title']), 'artist': r.get('artist', r['uploader']),
                            'expired': lambda: time.time() > expiry_time,
                            'album': r.get('album', 'YouTube'), 'length': r['duration'], 'ext': _f['ext'],
                            'art': r['thumbnail'], 'url': _f['url'], 'audio_url': audio_url, 'src': url}
                for webpage_url in get_yt_urls(r['id']): url_metadata[webpage_url] = metadata
                url_metadata[url] = metadata
                metadata_list.append(metadata)
    elif url.startswith('https://open.spotify.com'):
        # Handle Spotify URL (get metadata to search for track on YouTube)
        if url in url_metadata:
            metadata = url_metadata[url]
            query = f"{get_first_artist(metadata['artist'])} - {metadata['title']}"
            youtube_metadata = get_url_metadata(f'ytsearch:{query}', False)[0]
            metadata = {**youtube_metadata, **metadata}
            url_metadata[metadata['src']] = url_metadata[youtube_metadata['src']] = metadata
            metadata_list.append(metadata)
        else:
            # get a list of spotify tracks from the track/album/playlist Spotify URL
            spotify_tracks = get_spotify_tracks(url)
            if spotify_tracks:
                metadata = spotify_tracks[0]
                query = f"{get_first_artist(metadata['artist'])} - {metadata['title']}"
                youtube_metadata = get_url_metadata(f'ytsearch:{query}', False)[0]
                metadata = {**youtube_metadata, **metadata}
                url_metadata[metadata['src']] = url_metadata[youtube_metadata['src']] = metadata
                metadata_list.append(metadata)
                for spotify_track in islice(spotify_tracks, 1, None):
                    url_metadata[spotify_track['src']] = spotify_track
                    uris_to_scan.put(spotify_track['src'])
                    metadata_list.append(spotify_track)
    elif url.startswith('https://deezer.page.link') or url.startswith('https://www.deezer.com'):
        try:
            for metadata in get_deezer_tracks(url):
                url_metadata[metadata['src']] = metadata
                metadata_list.append(metadata)
        except LookupError:
            # login cookie not found
            # first time open the browser
            if not deezer_opened:
                Thread(target=webbrowser.open, daemon=True, args=['https://www.deezer.com/login']).start()
                tray_notify(gt('ERROR') + ': ' + gt('Not logged into deezer.com'))
                deezer_opened = True
            # fallback to deezer -> youtube
            if url in url_metadata:
                metadata = url_metadata[url]
                query = f"{get_first_artist(metadata['artist'])} - {metadata['title']}"
                youtube_metadata = get_url_metadata(f'ytsearch:{query}', False)[0]
                metadata = {**youtube_metadata, **metadata}
                url_metadata[metadata['src']] = url_metadata[youtube_metadata['src']] = metadata
                metadata_list.append(metadata)
            else:
                deezer_tracks = get_deezer_tracks(url, login=False)
                if deezer_tracks:
                    metadata = deezer_tracks[0]
                    query = f"{get_first_artist(metadata['artist'])} - {metadata['title']}"
                    youtube_metadata = get_url_metadata(f'ytsearch:{query}', False)[0]
                    metadata = {**youtube_metadata, **metadata}
                    url_metadata[metadata['src']] = url_metadata[youtube_metadata['src']] = metadata
                    metadata_list.append(metadata)
                    for deezer_track in islice(deezer_tracks, 1, None):
                        url_metadata[deezer_track['src']] = deezer_track
                        uris_to_scan.put(deezer_track['src'])
                        metadata_list.append(deezer_track)
    if metadata_list and fetch_art:
        # fetch and cache album art for first url
        metadata = metadata_list[0]
        if 'art' in metadata and 'art_data' not in metadata:
            url_metadata[metadata['src']]['art_data'] = base64.b64encode(requests.get(metadata['art']).content)
    return metadata_list


def play_url(url, position=0, autoplay=True, switching_device=False):
    global cast, playing_url, cast_last_checked
    global track_length, track_start, track_end, track_position, progress_bar_last_update
    metadata_list = get_url_metadata(url)
    if metadata_list:
        if len(metadata_list) > 1:
            # url was for multiple sources
            music_queue.popleft()
            music_queue.extendleft((metadata['src'] for metadata in reversed(metadata_list)))
        metadata = metadata_list[0]
        title, artist, album = str(metadata['title']), str(metadata['artist']), str(metadata['album'])
        ext = metadata['ext']
        url = metadata['audio_url'] if cast is None and 'audio_url' in metadata else metadata['url']
        thumbnail = metadata['art'] if 'art' in metadata else f'{get_ipv4()}/file?path=DEFAULT_ART'
        if cast is None:
            audio_player.play(url, start_playing=autoplay, start_from=position)
        else:
            cast_last_checked = time.time() + 60  # make sure background_tasks doesn't interfere
            with suppress(RuntimeError): cast.wait(timeout=WAIT_TIMEOUT)
            cast.set_volume(0 if settings['muted'] else settings['volume'] / 100)
            mc = cast.media_controller
            if mc.status.player_is_playing or mc.status.player_is_paused:
                mc.stop()
                mc.block_until_active(WAIT_TIMEOUT)
            _metadata = {'metadataType': 3, 'albumName': album, 'title': title, 'artist': artist}
            mc.play_media(url, f'video/{ext}', metadata=_metadata, thumb=thumbnail,
                          current_time=position, autoplay=autoplay)
            mc.block_until_active(WAIT_TIMEOUT)
            start_time = time.time()
            while mc.status.player_state not in {'PLAYING', 'PAUSED'}:
                time.sleep(0.2)
                if time.time() - start_time > 5: break  # show error?
        progress_bar_last_update = time.time()
        track_position = position
        track_length = metadata['length']
        track_start = time.time() - track_position
        track_end = track_start + track_length
        playing_url = True
        after_play(title, artist, autoplay, switching_device)
        return True
    tray_notify(gt('ERROR') + ': ' + gt('Could not play $URL').replace('$URL', url))
    return False


def play(uri, position=0, autoplay=True, switching_device=False):
    global track_start, track_end, track_length, track_position, music_queue, progress_bar_last_update, \
        cast_last_checked, playing_url
    while not os.path.exists(uri):
        if play_url(uri, position=position, autoplay=autoplay, switching_device=switching_device): return
        music_queue.remove(uri)
        if music_queue:
            uri = music_queue[0]
        else:
            return
        position = 0
    uri = uri.replace('\\', '/')
    playing_url = sar.alive = False
    cleaned_uri = 'some_file.' + uri.split('.')[-1]  # clean uri for log
    app_log.info(f'play: {cleaned_uri}, position={position}, autoplay={autoplay}, switching_device={switching_device}')
    try:
        track_length = get_length(uri)
    except InvalidAudioFile:
        tray_notify(f"ERROR: can't play {music_queue.popleft()}")
        if music_queue: play(music_queue[0])
        return
    metadata = get_metadata_wrapped(uri)
    # update metadata of track in case something changed
    all_tracks[uri] = metadata
    _volume = 0 if settings['muted'] else settings['volume'] / 100
    if cast is None:  # play locally
        audio_player.play(uri, volume=_volume, start_playing=autoplay, start_from=position)
    else:
        try:
            cast_last_checked = time.time() + 60  # make sure background_tasks doesn't interfere
            url_args = urllib.parse.urlencode({'path': uri})
            url = f'http://{get_ipv4()}:{Shared.PORT}/file?{url_args}'
            with suppress(RuntimeError):
                cast.wait(timeout=WAIT_TIMEOUT)
            cast.set_volume(_volume)
            mc = cast.media_controller
            metadata = {'title': str(metadata['title']), 'artist': str(metadata['artist']),
                        'albumName': str(metadata['album']), 'metadataType': 3}
            ext = uri.split('.')[-1]
            mc.play_media(url, f'audio/{ext}', current_time=position,
                          metadata=metadata, thumb=url + '&thumbnail_only=true', autoplay=autoplay)
            block_time = time.time()
            mc.block_until_active(WAIT_TIMEOUT + 1)
            if time.time() - block_time > WAIT_TIMEOUT:
                app_log.info('play: FAILED TO BLOCK UNTIL ACTIVE')
            start_time = time.time()
            while mc.status.player_state not in {'PLAYING', 'PAUSED'}:
                time.sleep(0.2)
                if time.time() - start_time > WAIT_TIMEOUT: break
            app_log.info(f'play: mc.status.player_state={mc.status.player_state}')
            progress_bar_last_update = time.time()
        except (UnsupportedNamespace, NotConnected, OSError):
            tray_notify(gt('ERROR') + ': ' + gt('Could not connect to cast device'))
            with suppress(UnsupportedNamespace):
                stop('play')
            return
    track_position = position
    track_start = time.time() - track_position
    track_end = track_start + track_length
    after_play(metadata['title'], metadata['artist'], autoplay, switching_device)


def queue_all():
    global update_gui_queue
    ignore_set = set(music_queue).union(next_queue).union(done_queue)
    temp_lst = list(index_all_tracks(update_global=False, ignore_files=ignore_set).keys())
    shuffle(temp_lst)
    music_queue.extend(temp_lst)
    update_gui_queue = True


def play_all(starting_files: tuple = None, queue_only=False):
    """
    Clears done queue, music queue,
    Adds starting files to music queue,
    [shuffle] queues files in the "library" with index_all_tracks (ignores starting_files)
    """
    global indexing_tracks_thread, music_queue
    if not queue_only:
        music_queue.clear()
        done_queue.clear()
    if starting_files is None: starting_files = []
    starting_files = list(get_audio_uris(starting_files))
    if indexing_tracks_thread is not None and indexing_tracks_thread.is_alive() and settings['notifications']:
        info = gt('INFO')
        tray_notify(f'{info}: ' + gt('Library indexing incomplete, only scanned files have been added'))
    music_queue.extend(index_all_tracks(False, set(starting_files)).keys())
    if music_queue:
        temp_list = list(music_queue)
        shuffle(temp_list)
        music_queue = deque(temp_list)
    music_queue.extendleft(reversed(starting_files))
    if not queue_only:
        if music_queue:
            play(music_queue[0])
        elif next_queue:
            playing_status.play()
            next_track()


def play_uris(uris: list, queue_uris=False, play_next=False, from_explorer=False):
    global update_gui_queue
    """
    Appends all music files in the provided uris (playlist names, folders, files, urls) to a temp list,
        which is shuffled if shuffled is enabled in settings, and then extends music_queue.
        Note: file/folder paths take precedence over playlist names
    If queue_only is false, the music queue and done queue are cleared,
        before files are added to the music_queue
    If queue_uris and play_next, play_next is used
    If from_explorer is true, then the whole music queue is shuffled (if setting enabled),
        except for the track that is currently playing
    """
    if not queue_uris and not play_next:
        music_queue.clear()
        done_queue.clear()
    temp_queue = list(get_audio_uris(uris))
    if play_next:
        if settings['shuffle']: better_shuffle(temp_queue)
        if settings['reversed_play_next']: next_queue.extendleft(temp_queue)
        else: next_queue.extend(temp_queue)
        return
    update_gui_queue = True
    if settings['shuffle'] * from_explorer:
        # if from_explorer make temp_queue should also include files in the queue
        temp_queue.extend(islice(music_queue, 1, None))
        shuffle(temp_queue)
        # remove all but first track if from_explorer
        for _ in range(len(music_queue) - 1): music_queue.pop()
    music_queue.extend(temp_queue)
    if not queue_uris and not play_next:
        if music_queue:
            play(music_queue[0])
        elif next_queue:
            playing_status.play()
            next_track()


def file_action(action='pf'):
    """
    action = {'pf': 'Play File(s)', 'pfn': 'Play File(s) Next', 'qf': 'Queue File(s)'}
    :param action: one of {'pf': 'Play File(s)', 'pfn': 'Play File(s) Next', 'qf': 'Queue File(s)'}
    :return:
    """
    global music_queue, next_queue, main_last_event, update_gui_queue
    initial_folder = settings['last_folder'] if settings['use_last_folder'] else DEFAULT_FOLDER
    # noinspection PyTypeChecker
    paths: tuple = Sg.popup_get_file(gt('Select Music File(s)'), no_window=True, initial_folder=initial_folder,
                                     multiple_files=True, file_types=AUDIO_FILE_TYPES, icon=WINDOW_ICON)
    if paths:
        settings['last_folder'] = os.path.dirname(paths[-1])
        app_log.info(f'file_action(action={action}), len(lst) is {len(paths)}')
        update_gui_queue = True
        main_last_event = Sg.TIMEOUT_KEY
        if action in {gt('Play File(s)'), 'pf'}:
            if settings['queue_library']:
                play_all(starting_files=paths)
            else:
                music_queue.clear()
                done_queue.clear()
                music_queue.extend(get_audio_uris(paths))
                if music_queue: play(music_queue[0])
        elif action in {gt('Queue File(s)'), 'qf'}:
            _start_playing = not music_queue
            music_queue.extend(get_audio_uris(paths))
            if _start_playing and music_queue: play(music_queue[0])
        elif action in {gt('Play File(s) Next'), 'pfn'}:
            if settings['reversed_play_next']:
                next_queue.extendleft(get_audio_uris(paths))
            else:
                next_queue.extend(get_audio_uris(paths))
            if playing_status.stopped() and not music_queue and next_queue:
                if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: cast.wait(timeout=WAIT_TIMEOUT)
                playing_status.play()
                next_track()
        else:
            raise ValueError('Expected one of: "Play File(s)", "Play File(s) Next", or "Queue File(s)"')
    else:
        main_last_event = 'file_action'


def folder_action(action='Play Folder'):
    """
    :param action: one of {'pf': 'Play Folder', 'qf': 'Queue Folder', 'pfn': 'Play Folder Next'}
    :return:
    """
    global music_queue, next_queue, main_last_event, update_gui_queue
    initial_folder = settings['last_folder'] if settings['use_last_folder'] else DEFAULT_FOLDER
    folder_path = Sg.popup_get_folder(gt('Select Folder'), initial_folder=initial_folder, no_window=True,
                                      icon=WINDOW_ICON)
    if folder_path:
        settings['last_folder'] = folder_path
        temp_queue = []
        files_to_queue = defaultdict(list)
        for file_path in get_audio_uris(folder_path):
            path = Path(file_path)
            files_to_queue[path.parent.as_posix()].append(path.name)
        if settings['shuffle']:
            for parent, files in files_to_queue.items():
                temp_queue.extend([os.path.join(parent, file_path) for file_path in files])
            shuffle(temp_queue)
        else:
            for parent, files in files_to_queue.items():
                files = sorted([os.path.join(parent, file_path) for file_path in files], key=natural_key_file)
                temp_queue.extend(files)
        app_log.info(f'folder_action: action={action}), len(lst) is {len(temp_queue)}')
        update_gui_queue = True
        main_last_event = Sg.TIMEOUT_KEY
        if not temp_queue:
            if settings['notifications']:
                tray_notify(gt('ERROR') + ': ' + gt('Folder does not contain audio files'))
        elif action in {gt('Play Folder'), 'pf'}:
            music_queue.clear()
            done_queue.clear()
            music_queue += temp_queue
            play(music_queue[0])
        elif action in {gt('Play Folder Next'), 'pfn'}:
            if settings['reversed_play_next']: next_queue.extendleft(temp_queue)
            else: next_queue.extend(temp_queue)
            if playing_status.stopped() and not music_queue and next_queue:
                if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: cast.wait(timeout=WAIT_TIMEOUT)
                playing_status.play()
                next_track()
        elif action in {gt('Queue Folder'), 'qf'}:
            music_queue.extend(temp_queue)
            if len(temp_queue) == len(music_queue) and not sar.alive: play(music_queue[0])
        else:
            error = f'Expected one of: "Play Folder", "Play Folder Next", or "Queue Folder". Got {action}'
            raise ValueError(error)
    else:
        main_last_event = 'folder_action'


def get_track_position():
    global track_position
    if cast is not None:
        if sar.alive: return track_length
        try:
            mc = cast.media_controller
            mc.update_status()
            if not mc.status.player_is_idle:
                track_position = mc.status.adjusted_current_time or (time.time() - track_start)
        except (UnsupportedNamespace, NotConnected, TypeError):
            if playing_status.playing():
                track_position = time.time() - track_start
            # don't calculate if playing status is NOT PLAYING or PAUSED
    elif playing_status.busy():
        track_position = audio_player.get_pos()
    return track_position


def pause():
    """
    Returns true if player was playing
    Returns false if player was not playing
    can be called from a non-main thread
    """
    global track_position
    if playing_status.playing():
        try:
            if cast is None:
                track_position = time.time() - track_start
                if audio_player.pause():
                    app_log.info('paused local audio player')
                else:
                    app_log.info('could not pause local audio player')
            else:
                mc = cast.media_controller
                mc.update_status()
                mc.pause()
                while not mc.status.player_is_paused: time.sleep(0.1)
                track_position = mc.status.adjusted_current_time
                app_log.info('paused cast device')
            playing_status.pause()
            if settings['discord_rpc'] and (music_queue or sar.alive):
                metadata = get_current_metadata()
                title, artist = metadata['title'], metadata['artist']
                with suppress(Exception):
                    rich_presence.update(state=gt('By') + f': {artist}', details=title,
                                         large_image='default', large_text='Paused',
                                         small_image='logo', small_text='Music Caster')
        except UnsupportedNamespace:
            stop('pause')
        refresh_tray()
        return True
    return False


def resume():
    global track_end, track_position, track_start
    if playing_status.paused():
        try:
            if cast is None:
                if audio_player.resume():
                    app_log.info('resumed playback')
                else:
                    app_log.info('failed to resume')
            else:
                mc = cast.media_controller
                mc.update_status()
                mc.play()
                mc.block_until_active(WAIT_TIMEOUT)
                while not mc.status.player_state == 'PLAYING': time.sleep(0.1)
                track_position = mc.status.adjusted_current_time
            track_start = time.time() - track_position
            track_end = track_start + track_length
            playing_status.play()
            metadata = get_current_metadata()
            title, artist = metadata['title'], get_first_artist(metadata['artist'])
            if settings['discord_rpc']:
                with suppress(Exception):
                    rich_presence.update(state=gt('By') + f': {artist}', details=title,
                                         large_image='default', large_text=gt('Listening'),
                                         small_image='logo', small_text='Music Caster')
            refresh_tray()
        except (UnsupportedNamespace, NotConnected):
            if music_queue: play(music_queue[0], position=track_position)
        return True
    return False


def stop(stopped_from: str, stop_cast=True):
    """
    can be called from a non-main thread
    does not check if playing_status is busy
    """
    global cast, track_start, track_end, track_position, playing_url
    app_log.info(f'Stop reason: {stopped_from}')
    # allow Windows to go to sleep
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    playing_status.stop()
    sar.alive = playing_url = False
    if settings['discord_rpc']:
        with suppress(Exception): rich_presence.clear()
    if cast is not None:
        if cast.app_id == APP_MEDIA_RECEIVER:
            mc = cast.media_controller
            if stop_cast:
                mc.stop()
                until_time = time.time() + 5  # 5 seconds
                status = mc.status
                while ((status.player_is_playing or status.player_is_paused)
                       and time.time() > until_time): time.sleep(0.1)
                if status.player_is_playing or status.player_is_paused: cast.quit_app()
            else:  # only when background tasks calls stop()
                # check if background tasks is wrong
                mc.update_status()
                if mc.is_playing:
                    playing_status.play()
                elif mc.is_paused:
                    playing_status.pause()
                return
    else:
        audio_player.stop()
    track_start = track_position = track_end = 0
    if not exit_flag: refresh_tray()


def next_track(from_timeout=False, times=1, forced=False):
    """
    :param from_timeout: whether next track is due to track ending
    :param times: number of times to go to next track
    :param forced: whether to ignore current playing status
    :return:
    """
    app_log.info(f'next_track(from_timeout={from_timeout})')
    if cast is not None and cast.app_id != APP_MEDIA_RECEIVER and not forced:
        playing_status.stop()
    elif (forced or playing_status.busy() and not sar.alive) and (next_queue or music_queue):
        # if repeat all or repeat is off or empty queue or manual next
        if not settings['repeat'] or not music_queue or not from_timeout:
            if settings['repeat']: change_settings('repeat', False)
            for _ in range(times):
                if music_queue: done_queue.append(music_queue.popleft())
                if next_queue: music_queue.insert(0, next_queue.popleft())
                # if queue is empty but repeat is all AND there are tracks in the done_queue
                if not music_queue and settings['repeat'] is False and done_queue:
                    music_queue.extend(done_queue)
                    done_queue.clear()
        try: play(music_queue[0])
        except IndexError: stop('next track')  # repeat is off / no tracks in queue


def prev_track(times=1, forced=False):
    app_log.info('prev_track()')
    if not forced and cast is not None and cast.app_id != APP_MEDIA_RECEIVER:
        playing_status.stop()
    elif forced or playing_status.busy() and not sar.alive:
        if done_queue:
            for _ in range(times):
                if settings['repeat']: change_settings('repeat', False)
                track = done_queue.pop()
                music_queue.insert(0, track)
        with suppress(IndexError):
            play(music_queue[0])


def background_tasks():
    """
    Startup tasks:
    - sends info
    - creates/removes shortcut
    - starts keyboard listener
    - Initializes YoutubeDL
    Periodic (While True) tasks:
    - checks for Chromecast status update
    - reloads settings.json if settings.json is modified
    - checks for music caster updates
    - scans files
    """
    global cast_last_checked, track_position, track_start, track_end, settings_last_modified
    global update_last_checked, latest_version, exit_flag, update_volume_slider, update_gui_queue
    if not settings.get('DEBUG', DEBUG): send_info()
    create_shortcut()  # threaded
    pynput.keyboard.Listener(on_press=on_press, on_release=on_release).start()  # daemon = True
    if not args.uris: ydl.add_default_info_extractors()
    while not exit_flag:
        # if settings.json was updated outside of Music Caster, reload settings
        if os.path.getmtime(SETTINGS_FILE) != settings_last_modified: load_settings()
        # Check cast every 5 seconds
        if cast is not None and time.time() - cast_last_checked > 5:
            with suppress(UnsupportedNamespace):
                if cast.app_id == APP_MEDIA_RECEIVER:
                    mc = cast.media_controller
                    mc.update_status()
                    is_playing, is_paused = mc.status.player_is_playing, mc.status.player_is_paused
                    is_stopped = mc.status.player_is_idle
                    if not is_stopped:
                        # handle scrubbing of music from the home app / out of date time position
                        if abs(mc.status.adjusted_current_time - track_position) > 0.5:
                            track_position = mc.status.adjusted_current_time
                            track_start = time.time() - track_position
                            track_end = track_start + track_length
                    if is_paused:
                        pause()  # pause() checks if playing status equals 'PLAYING'
                    elif is_playing:
                        resume()
                    elif is_stopped and playing_status.busy() and (track_end is None or time.time() - track_end > 1):
                        # if cast says nothing is playing, only stop if we are not at the end of the track
                        #  this will prevent false positives
                        stop('background tasks', False)
                    _volume = settings['volume']
                    cast_volume = round(cast.status.volume_level * 100, 1)
                    if _volume != cast_volume:
                        if cast_volume > 0.5 or cast_volume <= 0.5 and not settings['muted']:
                            # if volume was changed via Google Home App
                            _volume = change_settings('volume', cast_volume)
                            if _volume and settings['muted']: change_settings('muted', False)
                            if active_windows['main']: update_volume_slider = True
                elif playing_status.playing():
                    stop('background tasks; app not running')
            cast_last_checked = time.time()
            # don't check cast around the time the next track will start playing
            if track_end is not None and track_end - cast_last_checked < 10: cast_last_checked += 5
        if time.time() - update_last_checked > 216000:
            # never show a notification for the same latest version
            release = get_latest_release(latest_version)
            if release:
                latest_version = release['version']
                tray_notify('update_available', context=latest_version)
            update_last_checked = time.time()
        # scan at most 500 files per loop.
        # Testing on an i7-7700k, scanning ~1000 files would block for 5 seconds
        uris_scanned = 0
        while uris_scanned < 500 and not uris_to_scan.empty():
            uri = uris_to_scan.get().replace('\\', '/')
            if uri.startswith('http'):
                get_url_metadata(uri)
            else:
                all_tracks[uri] = get_metadata_wrapped(uri)
            uris_to_scan.task_done()
            uris_scanned += 1
            update_gui_queue = True
        # if no files were scanned, pause for 5 seconds
        else: time.sleep(5)


def on_press(key):
    global last_press
    key = str(key)
    PRESSED_KEYS.add(key)
    valid_shortcut = len(PRESSED_KEYS) == 4 and "'m'" in PRESSED_KEYS
    ctrl_clicked = 'Key.ctrl_l' in PRESSED_KEYS or 'Key.ctrl_r' in PRESSED_KEYS
    shift_clicked = 'Key.shift' in PRESSED_KEYS or 'Key.shift_r' in PRESSED_KEYS
    alt_clicked = 'Key.alt_l' in PRESSED_KEYS or 'Key.alt_r' in PRESSED_KEYS
    # Ctrl + Alt + Shift + M open up main window
    if valid_shortcut and ctrl_clicked and shift_clicked and alt_clicked:
        daemon_commands.put('__ACTIVATED__')
    if key not in {'<179>', '<176>', '<177>', '<178>'} or time.time() - last_press < 0.15: return
    if key == '<179>' and not pause(): resume()
    elif key == '<176>' and playing_status.busy(): next_track()
    elif key == '<177>' and playing_status.busy(): prev_track()
    elif key == '<178>': stop('keyboard shortcut')
    last_press = time.time()


def on_release(key):
    with suppress(KeyError): PRESSED_KEYS.remove(str(key))


def activate_main_window(selected_tab=None, url_option='url_play_immediately'):
    global active_windows, main_window, pl_name, pl_tracks
    # selected_tab can be 'tab_queue', ['tab_library'], 'tab_playlists', 'tab_timer', or 'tab_settings'
    app_log.info(f'activate_main_window: selected_tab={selected_tab}, already_active={active_windows["main"]}')
    if not active_windows['main']:
        active_windows['main'] = True
        lb_tracks = create_track_list()
        selected_value = lb_tracks[len(done_queue)] if lb_tracks and len(done_queue) < len(lb_tracks) else None
        mini_mode = settings['mini_mode']
        save_window_loc_key = 'main' + '_mini_mode' if mini_mode else ''
        window_location = get_window_location(save_window_loc_key)
        if settings['show_album_art']:
            size = COVER_MINI if mini_mode else COVER_NORMAL
            try:
                album_art_data = resize_img(get_current_album_art(), settings['theme']['background'], size).decode()
            except (UnidentifiedImageError, OSError):
                album_art_data = resize_img(DEFAULT_ART, settings['theme']['background'], size).decode()
        else:
            album_art_data = None
        window_margins = (0, 0) if mini_mode else (0, 0)
        metadata = get_current_metadata()
        title, artist, album = metadata['title'], get_first_artist(metadata['artist']), metadata['album']
        position = get_track_position()
        main_gui_layout = create_main(lb_tracks, selected_value, playing_status, settings, VERSION, timer,
                                      all_tracks_sorted_sort_key, title, artist, album, track_length=track_length,
                                      album_art_data=album_art_data, track_position=position)
        main_window = Sg.Window('Music Caster', main_gui_layout, grab_anywhere=mini_mode, no_titlebar=mini_mode,
                                finalize=True, icon=WINDOW_ICON, return_keyboard_events=True, use_default_focus=False,
                                margins=window_margins, keep_on_top=mini_mode and settings['mini_on_top'],
                                location=window_location)
        if not settings['mini_mode']:
            main_window['queue'].update(set_to_index=len(done_queue), scroll_to_index=len(done_queue))
            with suppress(IndexError):
                pl_name = list(settings['playlists'].keys())[0]
                pl_tracks = settings['playlists'][pl_name].copy()
            default_pl_tracks = [f'{i + 1}. {format_uri(pl_track)}' for i, pl_track in enumerate(pl_tracks)]
            main_window['pl_tracks'].update(values=default_pl_tracks)
            gui_lists = ['queue', 'pl_tracks']
            if settings['EXPERIMENTAL']: gui_lists.append('library')
            for gui_list in gui_lists:
                main_window[gui_list].bind('<Enter>', '_mouse_enter')
                main_window[gui_list].bind('<Leave>', '_mouse_leave')
            for input_key in ('url_input', 'pl_url_input', 'timer_input'):
                main_window[input_key].Widget.config(insertbackground=settings['theme']['text'])
        main_window['volume_slider'].bind('<Enter>', '_mouse_enter')
        main_window['volume_slider'].bind('<Leave>', '_mouse_leave')
        main_window['progress_bar'].bind('<Enter>', '_mouse_enter')
        main_window['progress_bar'].bind('<Leave>', '_mouse_leave')
        set_save_position_callback(main_window, save_window_loc_key)
    elif settings['mini_mode'] and selected_tab:
        change_settings('mini_mode', not settings['mini_mode'])
        active_windows['main'] = False
        main_window.close()
        return activate_main_window(selected_tab)
    if not settings['mini_mode'] and selected_tab is not None:
        main_window[selected_tab].select()
        if selected_tab == 'tab_timer': main_window['timer_input'].set_focus()
        if selected_tab == 'tab_url':
            with suppress(KeyError):
                main_window[url_option].update(True)
            main_window['url_input'].set_focus()
            default_text: str = pyperclip.paste()
            if default_text.startswith('http'):
                main_window['url_input'].update(value=default_text)
    steal_focus(main_window)
    main_window.normal()
    main_window.force_focus()


def cancel_timer():
    global timer
    timer = 0
    if settings['notifications']: tray_notify(gt('Timer cancelled'))


def locate_uri(selected_track_index=0, uri=None):
    with suppress(IndexError):
        if uri is None:
            if selected_track_index < 0:
                uri = done_queue[selected_track_index]
            elif (selected_track_index == 0 or selected_track_index > len(next_queue)) and music_queue:
                uri = music_queue[selected_track_index]
            elif 0 < selected_track_index <= len(next_queue):
                uri = next_queue[selected_track_index - 1]
            else:
                uri = ''
        if uri.startswith('http'):
            if uri.startswith('http'): Thread(target=webbrowser.open, daemon=True, args=[uri]).start()
        elif os.path.exists(uri):
            Popen(f'explorer /select,"{fix_path(uri)}"')


def exit_program():
    global exit_flag
    exit_flag = True
    main_window.close()
    tray_process_queue.put({'method': 'hide'})
    with suppress(UnsupportedNamespace, NotConnected):
        if cast is None:
            stop('exit program')
        elif cast is not None and cast.app_id == APP_MEDIA_RECEIVER:
            cast.quit_app()
    with suppress(Exception):
        rich_presence.close()
    if settings['persistent_queue']:
        save_queues()
        save_queue_thread.join()
    if settings['auto_update']: auto_update(False)
    tray_process.terminate()
    sys.exit()  # since auto_update might not sys.exit()


def playlist_action(playlist_name, action='play'):
    if playlist_name in playlists and playlists[playlist_name]:
        if action == 'play' or action == 'queue':
            if action == 'play':
                music_queue.clear()
                done_queue.clear()
            shuffle_from = len(music_queue)
            music_queue.extend(get_audio_uris(playlist_name))
            if settings['shuffle']: better_shuffle(music_queue, shuffle_from)
            if action == 'play' or shuffle_from == 0: play(music_queue[0])
        elif 'next':
            next_queue.extend(get_audio_uris(playlist_name))


def other_tray_actions(_tray_item):
    global cast, cast_last_checked, timer
    # this code checks if its time to go to the next track
    # this code checks if its time to stop playing music if a timer was set
    # if _tray_item.split('.', 1)[0].isdigit():  # if user selected a different device
    if _tray_item.endswith('::device') and not _tray_item.startswith(CHECK_MARK):
        with suppress(ValueError):
            change_device(device_names.index(_tray_item))
    elif _tray_item.endswith('::PL'):  # playlist
        playlist_action(_tray_item[:-4].replace('&&', '&'))
    elif _tray_item.endswith('::PF'):  # play folder
        if _tray_item == gt('Select Folder(s)') + '::PF':
            folder_action()
        else:
            Thread(target=play_uris, name='PlayFolder', daemon=True,
                   args=[[music_folders[tray_folders.index(_tray_item) - 1]]]).start()
    elif playing_status.playing() and not sar.alive and time.time() > track_end:
        next_track(from_timeout=time.time() > track_end)
    elif timer and time.time() > timer:
        stop('timer')
        timer = 0
        if settings['timer_shut_down']:
            if platform.system() == 'Windows':
                os.system('shutdown /p /f')
            else:
                os.system('shutdown -h now')
        elif settings['timer_hibernate']:
            if platform.system() == 'Windows': os.system(r'rundll32.exe powrprof.dll,SetSuspendState Hibernate')
        elif settings['timer_sleep']:
            if platform.system() == 'Windows': os.system('rundll32.exe powrprof.dll,SetSuspendState 0,1,0')


def reset_mouse_hover():
    global mouse_hover
    mouse_hover = ''


def reset_progress():
    # NOTE: needs to be in main thread
    main_window['progress_bar'].update(value=0)
    main_window['time_elapsed'].update('0:00')
    main_window['time_left'].update('0:00')
    main_window.refresh()


def read_main_window():
    global main_last_event, mouse_hover, update_volume_slider, progress_bar_last_update
    global track_position, track_start, track_end, timer, main_window, update_gui_queue
    global tray_playlists, pl_tracks, pl_name, playlists, music_queue, done_queue
    # make if statements into dict mapping
    main_event, main_values = main_window.read(timeout=200)
    if (main_event in {None, 'Escape:27'} and
            main_last_event not in {'file_action', 'folder_action', 'pl_add_tracks', 'add_music_folder'}
            or main_values is None):
        main_window.close()
        active_windows['main'] = False
        return False
    main_value = main_values.get(main_event)
    if 'mouse_leave' not in main_event and 'mouse_enter' not in main_event and main_event != Sg.TIMEOUT_KEY:
        main_last_event = main_event
    gui_title = main_window['title'].DisplayText
    update_progress_bar_text, title, artist, album = False, gt('Nothing Playing'), '', ''
    if playing_status.busy() and (sar.alive or music_queue):
        metadata = get_current_metadata()
        title, artist, album = metadata['title'], get_first_artist(metadata['artist']), metadata['album']
        if settings['show_track_number']:
            with suppress(KeyError):
                track_number = metadata['track_number']
                title = f'{track_number}. {title}'
    # usually if music stops playing or another track starts playing
    if gui_title != title:
        if settings['mini_mode']: title = truncate_title(title)
        main_window['title'].update(title)
        main_window['artist'].update(artist)
        # update album title if not in mini-mode
        if not settings['mini_mode']: main_window['album'].update(album)
        if settings['show_album_art']:
            size = COVER_MINI if settings['mini_mode'] else COVER_NORMAL
            try:
                album_art_data = resize_img(get_current_album_art(), settings['theme']['background'], size).decode()
            except (UnidentifiedImageError, OSError):
                album_art_data = resize_img(DEFAULT_ART, settings['theme']['background'], size).decode()
            main_window['album_art'].update(data=album_art_data)
        update_gui_queue = True
    # update timer text if timer is old
    if not settings['mini_mode'] and timer == 0 and main_window['timer_text'].metadata:
        main_window['timer_text'].update('No Timer Set')
        main_window['timer_text'].metadata = False
        main_window['cancel_timer'].update(visible=False)
    # check updates from global variables
    if update_gui_queue and not settings['mini_mode']:
        update_gui_queue = False
        dq_len = len(done_queue)
        lb_tracks = create_track_list()
        main_window['queue'].update(values=lb_tracks, set_to_index=dq_len, scroll_to_index=dq_len)
        pl_formatted = [f'{i + 1}. {format_uri(pl_track)}' for i, pl_track in enumerate(pl_tracks)]
        main_window['pl_tracks'].update(values=pl_formatted)
    if update_volume_slider:
        if settings['volume'] and settings['muted']:
            main_window['mute'].update(image_data=VOLUME_IMG)
            main_window['mute'].set_tooltip('mute')
        main_window['volume_slider'].update(settings['volume'])
        update_volume_slider = False
    # update repeat button (image) if button metadata differs from settings
    if settings['repeat'] != main_window['repeat'].metadata: update_repeat_button()
    # update shuffle button (image) if button metadata differs from settings
    if settings['shuffle'] != main_window['shuffle'].metadata:
        shuffle_image_data = SHUFFLE_ON if settings['shuffle'] else SHUFFLE_OFF
        main_window['shuffle'].update(image_data=shuffle_image_data)
        main_window['shuffle'].metadata = settings['shuffle']
    # handle events here
    if main_event.startswith('MouseWheel'):
        main_event = main_event.split(':', 1)[1]
        delta = {'Up': 5, 'Down': -5}.get(main_event, 0)
        if mouse_hover == 'progress_bar':
            if playing_status.busy():
                get_track_position()
                new_position = min(max(track_position + delta, 0), track_length)
                main_window['progress_bar'].update(value=new_position)
                main_values['progress_bar'] = new_position
                main_event = 'progress_bar'
        elif mouse_hover in {'', 'volume_slider'}:  # not in another tab
            new_volume = min(max(0, main_values['volume_slider'] + delta), 100)
            change_settings('volume', new_volume)
            if settings['muted']:
                main_window['mute'].update(image_data=VOLUME_IMG)
                main_window['mute'].set_tooltip('mute')
                change_settings('muted', False)
            update_volume(new_volume)
        main_window.refresh()
    # needs to be in its own if statement because it tell the progress bar to update later on
    if main_event in {'j', 'l'} and (settings['mini_mode'] or
                                     main_values['tab_group'] not in {'tab_timer', 'tab_playlists'}):
        if playing_status.busy():
            delta = {'j': -settings['scrubbing_delta'], 'l': settings['scrubbing_delta']}[main_event]
            get_track_position()
            new_position = min(max(track_position + delta, 0), track_length)
            main_window['progress_bar'].update(value=new_position)
            main_values['progress_bar'] = new_position
            main_event = 'progress_bar'
            main_window.refresh()
    if main_event == Sg.TIMEOUT_KEY: pass
    # change/select tabs
    elif main_event == '1:49' and not settings['mini_mode']:  # Queue tab [Ctrl + 1]
        main_window['tab_queue'].select()
    elif (main_event == '2:50' and not settings['mini_mode'] or  # URL tab [Ctrl + 2]
          main_event == 'tab_group' and main_values['tab_group'] == 'tab_url'):
        main_window['tab_url'].select()
        main_window['url_input'].set_focus()
        default_text: str = pyperclip.paste()
        if default_text.startswith('http'):
            main_window['url_input'].update(value=default_text)
    elif (main_event == '3:51' and not settings['mini_mode'] or  # Playlists tab [Ctrl + 3]:
          main_event == 'tab_group' and main_values['tab_group'] == 'tab_playlists'):
        main_window['tab_playlists'].select()
        main_window['playlist_combo'].set_focus()
    elif (main_event == '4:52' and not settings['mini_mode'] or  # Timer Tab [Ctrl + 4]
          main_event == 'tab_group' and main_values['tab_group'] == 'tab_timer'):
        main_window['tab_timer'].select()
        main_window['timer_input'].set_focus()
    elif main_event == '5:53' and not settings['mini_mode']:  # Settings tab [Ctrl + 5]
        main_window['tab_settings'].select()
    elif main_event in {'progress_bar_mouse_enter', 'queue_mouse_enter', 'pl_tracks_mouse_enter',
                        'volume_slider_mouse_enter', 'library_mouse_enter'}:
        if main_event in {'progress_bar_mouse_enter', 'volume_slider_mouse_enter'} and settings['mini_mode']:
            main_window.grab_any_where_off()
        mouse_hover = '_'.join(main_event.split('_')[:-2])
    elif main_event in {'progress_bar_mouse_leave', 'queue_mouse_leave', 'pl_tracks_mouse_leave',
                        'volume_slider_mouse_leave', 'library_mouse_leave'}:
        if main_event in {'progress_bar_mouse_leave', 'volume_slider_mouse_leave'} and settings['mini_mode']:
            main_window.grab_any_where_on()
        mouse_hover = '' if main_event != 'volume_slider_mouse_leave' else mouse_hover
    elif (main_event == 'pause/resume' or main_event == 'k' and
          main_values.get('tab_group') not in {'tab_timer', 'tab_playlists'}):
        if playing_status.paused(): resume()
        elif playing_status.playing(): pause()
        elif music_queue: play(music_queue[0])
        else: play_all()
    elif main_event == 'next' and playing_status.busy():
        reset_progress()
        next_track()
    elif main_event == 'prev' and playing_status.busy():
        reset_progress()
        prev_track()
    elif main_event == 'shuffle':
        shuffle_option = change_settings('shuffle', not settings['shuffle'])
        shuffle_image_data = SHUFFLE_ON if shuffle_option else SHUFFLE_OFF
        main_window['shuffle'].update(image_data=shuffle_image_data)
        main_window['shuffle'].metadata = shuffle_option
        if shuffle_option: shuffle_queue()
        else: un_shuffle_queue()
    elif main_event in {'repeat', 'r:82'}:
        cycle_repeat(True)
    elif (main_event == 'volume_slider' or ((main_event in {'a', 'd'} or main_event.isdigit())
          and (settings['mini_mode'] or main_values['tab_group'] not in {'tab_timer', 'tab_playlists'}))):
        # User scrubbed volume bar or pressed (while on Tab 1 or in mini mode)
        delta = 0
        if main_event.isdigit():
            new_volume = int(main_event) * 10
        else:
            if main_event == 'a':
                delta = -5
            elif main_event == 'd':
                delta = 5
            new_volume = main_values['volume_slider'] + delta
        change_settings('volume', new_volume)
        # since volume bar was moved above 0, unmute if muted
        if settings['muted'] and new_volume:
            main_window['mute'].update(image_data=VOLUME_IMG)
            main_window['mute'].set_tooltip(gt('mute'))
            change_settings('muted', False)
        update_volume(new_volume)
    elif main_event in {'mute', 'm:77'}:  # toggle mute
        muted = change_settings('muted', not settings['muted'])
        if muted:
            main_window['mute'].update(image_data=VOLUME_MUTED_IMG)
            main_window['mute'].set_tooltip(gt('unmute'))
            update_volume(0)
        else:
            main_window['mute'].update(image_data=VOLUME_IMG)
            main_window['mute'].set_tooltip(gt('mute'))
            update_volume(settings['volume'])
    elif main_event in {'Up:38', 'Down:40', 'Prior:33', 'Next:34'}:
        if not settings['mini_mode']:
            focused_element = main_window.FindElementWithFocus()
            move = {'Up:38': -1, 'Down:40': 1, 'Prior:33': -3, 'Next:34': 3}[main_event]
            if focused_element == main_window['queue'] and main_values['queue']:
                new_i = main_window['queue'].get_indexes()[0] + move
                new_i = min(max(new_i, 0), len(music_queue) - 1)
                main_window['queue'].update(set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
            elif focused_element == main_window['pl_tracks'] and main_values['pl_tracks']:
                new_i = main_window['pl_tracks'].get_indexes()[0] + move
                new_i = min(max(new_i, 0), len(pl_tracks) - 1)
                main_window['pl_tracks'].update(set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif main_event == 'queue' and main_value:
        with suppress(ValueError):
            selected_uri_index = main_window['queue'].get_indexes()[0]
            if selected_uri_index <= len(done_queue):
                prev_track(times=len(done_queue) - selected_uri_index, forced=True)
            else:
                next_track(times=selected_uri_index - len(done_queue), forced=True)
            updated_list = create_track_list()
            dq_len = len(done_queue)
            main_window['queue'].update(values=updated_list, set_to_index=dq_len, scroll_to_index=dq_len)
            reset_progress()
    elif main_event in {'album', 'title', 'artist'} and playing_status.busy(): locate_uri()
    elif main_event in {'locate_uri', 'e:69'}:
        if not settings['mini_mode'] and main_window['queue'].get_indexes():
            selected_uri_index = main_window['queue'].get_indexes()[0] - len(done_queue)
        else: selected_uri_index = 0
        locate_uri(selected_uri_index)
    elif main_event == 'move_to_next_up' and main_values['queue']:
        index_to_move = main_window['queue'].get_indexes()[0]
        dq_len = len(done_queue)
        nq_len = len(next_queue)
        if index_to_move < dq_len:
            track = done_queue[index_to_move]
            del done_queue[index_to_move]
            if settings['reversed_play_next']: next_queue.insert(0, track)
            else: next_queue.append(track)
            updated_list = create_track_list()
            main_window['queue'].update(values=updated_list, set_to_index=len(done_queue) + len(next_queue),
                                        scroll_to_index=max(len(done_queue) + len(next_queue) - 16, 0))
            save_queues()
        elif index_to_move > dq_len + nq_len:
            track = music_queue[index_to_move - dq_len - nq_len]
            del music_queue[index_to_move - dq_len - nq_len]
            if settings['reversed_play_next']: next_queue.insert(0, track)
            else: next_queue.append(track)
            updated_list = create_track_list()
            main_window['queue'].update(values=updated_list, set_to_index=dq_len + len(next_queue),
                                        scroll_to_index=max(len(done_queue) + len(next_queue) - 3, 0))
            save_queues()
    elif main_event == 'move_up' and main_values['queue']:
        index_to_move = main_window['queue'].get_indexes()[0]
        new_i = index_to_move - 1
        dq_len = len(done_queue)
        nq_len = len(next_queue)
        if index_to_move < dq_len and new_i >= 0:  # move within dq
            # swap places
            done_queue[index_to_move], done_queue[new_i] = done_queue[new_i], done_queue[index_to_move]
        elif index_to_move == dq_len and done_queue:  # move index -1 to 1
            if next_queue:
                next_queue.insert(1, done_queue.pop())
            else:
                music_queue.insert(1, done_queue.pop())
        elif index_to_move == dq_len + 1:  # move 1 to -1
            if next_queue:
                done_queue.append(next_queue.popleft())
            else:
                track = music_queue[1]
                del music_queue[1]
                done_queue.append(track)
        elif next_queue and dq_len < index_to_move <= nq_len + dq_len:  # within next_queue
            nq_i = new_i - dq_len - 1
            # swap places, NOTE: could be more efficient using a custom deque with O(n) swaps instead of O(2n)
            next_queue[nq_i], next_queue[nq_i + 1] = next_queue[nq_i + 1], next_queue[nq_i]
        elif next_queue and index_to_move == dq_len + nq_len + 1:  # moving into next queue
            track = music_queue[1]
            del music_queue[1]
            next_queue.insert(nq_len - 1, track)
        elif new_i >= 0:  # moving within mq
            mq_i = new_i - dq_len - nq_len
            music_queue[mq_i], music_queue[mq_i + 1] = music_queue[mq_i + 1], music_queue[mq_i]
        else:
            new_i = max(new_i, 0)
        updated_list = create_track_list()
        main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 7, 0))
        save_queues()
    elif main_event == 'move_down' and main_values['queue']:
        index_to_move = main_window['queue'].get_indexes()[0]
        dq_len, nq_len, mq_len = len(done_queue), len(next_queue), len(music_queue)
        if index_to_move < dq_len + nq_len + mq_len - 1:
            new_i = index_to_move + 1
            if index_to_move == dq_len - 1:  # move index -1 to 1
                if next_queue:
                    next_queue.insert(0, done_queue.pop())
                else:
                    music_queue.insert(1, done_queue.pop())
            elif index_to_move < dq_len:  # move within dq
                done_queue[index_to_move], done_queue[new_i] = done_queue[new_i], done_queue[index_to_move]
            elif index_to_move == dq_len:  # move 1 to -1
                if next_queue:
                    done_queue.append(next_queue.popleft())
                else:
                    track = music_queue[1]
                    del music_queue[1]
                    done_queue.append(track)
            elif next_queue and index_to_move == dq_len + nq_len:  # moving into music_queue
                music_queue.insert(2, next_queue.pop())
            elif index_to_move < dq_len + nq_len + 1:  # within next_queue
                nq_i = index_to_move - dq_len - 1
                next_queue[nq_i], next_queue[nq_i - 1] = next_queue[nq_i - 1], next_queue[nq_i]
            else:  # within music_queue
                mq_i = new_i - dq_len - nq_len
                # swap places
                music_queue[mq_i], music_queue[mq_i - 1] = music_queue[mq_i - 1], music_queue[mq_i]
            updated_list = create_track_list()
            main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
            save_queues()
    elif main_event == 'remove_track' and main_values['queue']:
        index_to_remove = main_window['queue'].get_indexes()[0]
        dq_len, nq_len, mq_len = len(done_queue), len(next_queue), len(music_queue)
        if index_to_remove < dq_len:
            del done_queue[index_to_remove]
        elif index_to_remove == dq_len:
            # remove the "0. XXXX" track that could be playing right now
            music_queue.popleft()
            if next_queue: music_queue.insert(0, next_queue.popleft())
            # if queue is empty but repeat is all AND there are tracks in the done_queue
            if not music_queue and settings['repeat'] is False and done_queue:
                music_queue.extend(done_queue)
                done_queue.clear()
            # start playing new track if a track was being played
            if not sar.alive:
                if music_queue and playing_status.busy():
                    play(music_queue[0])
                else:
                    stop('remove_track')
        elif index_to_remove <= nq_len + dq_len:
            del next_queue[index_to_remove - dq_len - 1]
        elif index_to_remove < nq_len + mq_len + dq_len:
            del music_queue[index_to_remove - dq_len - nq_len]
        updated_list = create_track_list()
        new_i = min(len(updated_list), index_to_remove)
        main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif main_event == 'file_option':
        main_window['file_action'].update(text=main_values['file_option'])
    elif main_event == 'folder_option':
        main_window['folder_action'].update(text=main_values['folder_option'])
    elif main_event == 'file_action':
        Thread(target=file_action, name='FileAction', daemon=True,
               args=[main_values['file_option']]).start()
    elif main_event == 'folder_action':
        Thread(target=folder_action, name='FolderAction', daemon=True,
               args=[main_values['folder_option']]).start()
    elif main_event == 'playlist_action':
        playlist_action(main_values['playlists'])
    elif main_event == 'play_all':
        already_queueing = False
        for thread in threading.enumerate():
            if thread.name in {'QueueAll', 'PlayAll'} and thread.is_alive():
                already_queueing = True
                break
        if not already_queueing: Thread(target=play_all, name='PlayAll', daemon=True).start()
    elif main_event == 'queue_all':
        already_queueing = False
        for thread in threading.enumerate():
            if thread.name in {'QueueAll', 'PlayAll'} and thread.is_alive():
                already_queueing = True
                break
        if not already_queueing: Thread(target=queue_all, name='QueueAll', daemon=True).start()
    elif main_event == 'mini_mode':
        change_settings('mini_mode', not settings['mini_mode'])
        active_windows['main'] = False
        main_window.close()
        activate_main_window()
    elif main_event == 'clear_queue':
        reset_progress()
        main_window['queue'].update(values=[])
        if playing_status.busy(): stop('clear queue')
        music_queue.clear()
        next_queue.clear()
        done_queue.clear()
        save_queues()
    elif main_event == 'save_queue':
        pl_tracks = []
        pl_tracks.extend(done_queue)
        if music_queue: pl_tracks.append(music_queue[0])
        pl_tracks.extend(next_queue)
        pl_tracks.extend(islice(music_queue, 1, None))
        formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
        pl_name = ''
        main_window['tab_playlists'].select()
        main_window['playlist_name'].set_focus()
        main_window['playlist_name'].update(value=pl_name)
        main_window['pl_tracks'].update(values=formatted_tracks, set_to_index=0)
        main_window['pl_move_up'].update(disabled=not pl_tracks)
        main_window['pl_move_down'].update(disabled=not pl_tracks)
    # elif main_event == 'library':  # TODO
    elif main_event == 'progress_bar' and not sar.alive:
        if playing_status.stopped():
            main_window['progress_bar'].update(disabled=True, value=0)
            return
        else:
            new_position = main_values['progress_bar']
            track_position = new_position
            if cast is not None:
                try:
                    cast.media_controller.update_status()
                except UnsupportedNamespace:
                    cast.wait()
                if cast.is_idle and music_queue:
                    play(music_queue[0], position=new_position)
                else:
                    cast.media_controller.seek(new_position)
                    playing_status.play()
            else:
                audio_player.set_pos(new_position)
            update_progress_bar_text = True
            track_start = time.time() - track_position
            track_end = track_start + track_length
    # main window settings tab
    elif main_event == 'email':
        Thread(target=webbrowser.open, daemon=True, args=[create_email_url()]).start()
    elif main_event == 'web_gui':
        Thread(target=webbrowser.open, daemon=True, args=[f'http://{get_ipv4()}:{Shared.PORT}']).start()
    # toggle settings
    elif main_event in {'auto_update', 'notifications', 'discord_rpc', 'run_on_startup', 'folder_cover_override',
                        'folder_context_menu', 'save_window_positions', 'populate_queue_startup', 'lang',
                        'show_track_number', 'persistent_queue', 'flip_main_window', 'vertical_gui', 'use_last_folder',
                        'show_album_art', 'reversed_play_next', 'scan_folders', 'show_queue_index', 'queue_library'}:
        change_settings(main_event, main_value)
        if main_event == 'run_on_startup':
            create_shortcut()
        elif main_event == 'persistent_queue':
            if main_value: save_queues()
            else: change_settings('queues', {'done': [], 'music': [], 'next': []})
            change_settings('populate_queue_startup', False)
            main_window['populate_queue_startup'].update(value=False)
        elif main_event in 'populate_queue_startup':
            main_window['persistent_queue'].update(value=False)
            change_settings('persistent_queue', False)
        elif main_event == 'discord_rpc':
            with suppress(Exception):
                if main_value and playing_status.busy():
                    metadata = url_metadata['SYSTEM_AUDIO'] if sar.alive else get_uri_metadata(music_queue[0])
                    title, artist = metadata['title'], get_first_artist(metadata['artist'])
                    rich_presence.connect()
                    rich_presence.update(state=gt('By') + f': {artist}', details=title,
                                         large_image='default', large_text='Listening',
                                         small_image='logo', small_text='Music Caster')
                elif not main_value:
                    rich_presence.clear()
        elif main_event in {'show_album_art', 'vertical_gui', 'flip_main_window'}:
            # re-render main GUI
            active_windows['main'] = False
            main_window.close()
            activate_main_window('tab_settings')
        elif main_event in {'show_track_number', 'show_queue_index'}:
            update_gui_queue = True
        elif main_event == 'scan_folders' and main_value:
            index_all_tracks()
        elif main_event == 'folder_cover_override':
            size = COVER_MINI if settings['mini_mode'] else COVER_NORMAL
            try:
                album_art_data = resize_img(get_current_album_art(), settings['theme']['background'], size).decode()
            except (UnidentifiedImageError, OSError):
                album_art_data = resize_img(DEFAULT_ART, settings['theme']['background'], size).decode()
            main_window['album_art'].update(data=album_art_data)
        elif main_event == 'lang':
            Shared.lang = main_value
            active_windows['main'] = False
            main_window.close()
            activate_main_window('tab_settings')
            refresh_tray()
    elif main_event == 'remove_music_folder' and main_values['music_folders']:
        selected_item = main_values['music_folders'][0]
        with suppress(ValueError):
            settings['music_folders'].remove(selected_item)
            main_window['music_folders'].update(settings['music_folders'])
            refresh_tray()
            save_settings()
            if settings['scan_folders']: index_all_tracks()
    elif main_event == 'add_music_folder':
        main_value = main_value.replace('\\', '/')  # sanitize
        if main_value not in music_folders and os.path.exists(main_value):
            settings['music_folders'].append(main_value)
            main_window['music_folders'].update(settings['music_folders'])
            refresh_tray()
            save_settings()
            if settings['scan_folders']: index_all_tracks()
    elif main_event in {'settings_file', 'o:79'}:
        try:
            os.startfile(SETTINGS_FILE)
        except OSError:
            Popen(f'explorer /select,"{fix_path(SETTINGS_FILE)}"')
    elif main_event == 'changelog_file':
        with suppress(FileNotFoundError):
            os.startfile('changelog.txt')
    elif main_event == 'music_folders':
        with suppress(IndexError):
            Popen(f'explorer "{fix_path(main_values["music_folders"][0])}"')
    # url tab
    elif (main_event in {'\r', 'special 16777220', 'special 16777221', 'url_submit'}
          and main_values.get('tab_group', None) == 'tab_url' and main_values['url_input']):
        url_to_insert = main_values['url_input']
        if main_values['url_play'] or not music_queue:
            music_queue.insert(0, url_to_insert)
            play(url_to_insert)
        elif main_values['url_queue']:
            music_queue.append(url_to_insert)
            uris_to_scan.put(url_to_insert)
        else:  # add to next queue
            if settings['reversed_play_next']: next_queue.insert(0, url_to_insert)
            else: next_queue.append(url_to_insert)
            uris_to_scan.put(url_to_insert)
        main_window['url_input'].update(value='')
        main_window['url_input'].set_focus()
        update_gui_queue = True
    # timer tab
    elif main_event == 'cancel_timer':
        main_window['timer_text'].update('No Timer Set')
        main_window['timer_text'].metadata = False
        main_window['timer_error'].update(visible=False)
        main_window['cancel_timer'].update(visible=False)
    # handle enter/submit event
    elif (main_event in {'\r', 'special 16777220', 'special 16777221', 'timer_submit'}
          and main_values.get('tab_group', None) == 'tab_timer'):
        try:
            timer_value: str = main_values['timer_input']
            if timer_value.isdigit():
                seconds = abs(float(main_values['timer_input'])) * 60
            elif timer_value.count(':') == 1:
                # parse out any PM and AM's
                timer_value = timer_value.strip().upper().replace(' ', '').replace('PM', '').replace('AM', '')
                to_stop = datetime.strptime(timer_value + time.strftime(',%Y,%m,%d,%p'), '%I:%M,%Y,%m,%d,%p')
                current_time = datetime.now()
                current_time = current_time.replace(second=0)
                seconds_delta = (to_stop - current_time).total_seconds()
                if seconds_delta < 0: seconds_delta += 43200  # add 12 hours
                seconds = seconds_delta
            else:
                raise ValueError()
            timer = time.time() + seconds
            timer_set_to = datetime.now().replace(second=0) + timedelta(seconds=seconds)
            if platform.system() == 'Windows':
                timer_set_to = timer_set_to.strftime('%#I:%M %p')
            else:
                timer_set_to = timer_set_to.strftime('%-I:%M %p')  # Linux
            main_window['timer_text'].update(f'Timer set for {timer_set_to}')
            main_window['timer_text'].metadata = True
            main_window['cancel_timer'].update(visible=True)
            main_window['timer_error'].update(visible=False)
            main_window['timer_input'].update(value='')
            main_window['timer_input'].set_focus()
        except ValueError:
            # flash timer error
            for i in range(3):
                main_window['timer_error'].update(visible=True, text_color='#ffcccb')
                main_window.read(10)
                main_window['timer_error'].update(text_color='red')
                main_window.read(10)
            main_window['timer_input'].set_focus()
    elif main_event in {'shut_down', 'hibernate', 'sleep', 'timer_stop'}:
        change_settings('timer_hibernate', main_values['hibernate'])
        change_settings('timer_sleep', main_values['sleep'])
        change_settings('timer_shut_down', main_values['shut_down'])
    # playlist tab
    elif main_event == 'playlist_combo':
        # user selected a playlist from the drop-down
        pl_name = main_value if main_value in playlists else ''
        pl_tracks = playlists.get(pl_name, []).copy()
        main_window['playlist_name'].update(value=pl_name)
        formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
        main_window['pl_tracks'].update(values=formatted_tracks, set_to_index=0)
        main_window['pl_save'].update(disabled=pl_name == '')
        main_window['pl_rm_items'].update(disabled=not pl_tracks)
        main_window['pl_move_up'].update(disabled=not pl_tracks)
        main_window['pl_move_down'].update(disabled=not pl_tracks)
    elif main_event in {'new_pl', 'n:78'}:
        pl_name, pl_tracks = '', []
        main_window['playlist_name'].update(value=pl_name)
        main_window['playlist_name'].set_focus()
        main_window['pl_tracks'].update(values=pl_tracks, set_to_index=0)
        main_window['pl_save'].update(disabled=pl_name == '')
        main_window['playlist_combo'].update(value='')
        main_window['pl_rm_items'].update(disabled=True)
        main_window['pl_move_up'].update(disabled=True)
        main_window['pl_move_down'].update(disabled=True)
    elif main_event == 'export_pl':
        if main_values['playlist_combo'] and playlists.get(main_values['playlist_combo']):
            playlist_path = export_playlist(main_values['playlist_combo'], playlists[main_values['playlist_combo']])
            locate_uri(uri=playlist_path)
    elif main_event == 'del_pl':
        pl_name = main_values.get('playlist_combo', '')
        if pl_name in playlists:
            del playlists[pl_name]
        playlist_names = tuple(settings['playlists'].keys())
        pl_name = playlist_names[0] if playlist_names else ''
        main_window['playlist_combo'].update(value=pl_name, values=playlist_names)
        pl_tracks = playlists.get(pl_name, []).copy()
        formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
        # update playlist editor
        main_window['playlist_name'].update(value=pl_name)
        main_window['pl_tracks'].update(values=formatted_tracks, set_to_index=0)
        main_window['pl_save'].update(disabled=pl_name == '')
        main_window['play_pl'].update(disabled=pl_name == '')
        main_window['queue_pl'].update(disabled=pl_name == '')
        main_window['pl_rm_items'].update(disabled=not pl_tracks)
        main_window['pl_move_up'].update(disabled=not pl_tracks)
        main_window['pl_move_down'].update(disabled=not pl_tracks)
        save_settings()
        refresh_tray()
    elif main_event == 'play_pl':
        temp_lst = playlists.get(main_values['playlist_combo'], [])
        if temp_lst:
            done_queue.clear()
            music_queue.clear()
            music_queue.extend(temp_lst)
            if settings['shuffle']: shuffle(music_queue)
            play(music_queue[0])
    elif main_event == 'queue_pl':
        playlist_action(main_values['playlist_combo'], 'queue')
        update_gui_queue = True
    elif main_event in {'pl_save', 's:83'}:  # save playlist
        if main_values['playlist_name']:
            save_name = main_values['playlist_name']
            if pl_name != save_name:
                # if user is renaming a playlist, remove old data
                if pl_name in playlists: del playlists[pl_name]
                pl_name = save_name
            playlists[pl_name] = pl_tracks
            # sort playlists alphabetically
            playlists = settings['playlists'] = {k: playlists[k] for k in sorted(playlists.keys())}
            playlist_names = tuple(playlists.keys())
            main_window['playlist_combo'].update(value=pl_name, values=playlist_names, visible=True)
            main_window['play_pl'].update(disabled=False)
            main_window['queue_pl'].update(disabled=False)
        save_settings()
        refresh_tray()
    elif main_event == 'playlist_name':
        main_window['pl_save'].update(disabled=main_values['playlist_name'] == '')
    elif main_event in {'pl_rm_items', 'r:82'}:  # remove item from playlist
        if main_values['pl_tracks']:
            selected_items = main_values['pl_tracks']
            smallest_i = max(len(selected_items) - 1, 0)
            # remove tracks from bottom to top so that we don't have to worry about adjusting other indices
            for item_name in reversed(selected_items):
                index_removed = int(item_name.split('. ', 1)[0]) - 1
                if index_removed < len(pl_tracks):
                    pl_tracks.pop(index_removed)
                    smallest_i = index_removed - 1
            formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
            scroll_to_index = max(smallest_i - 3, 0)
            main_window['pl_tracks'].update(formatted_tracks, set_to_index=smallest_i, scroll_to_index=scroll_to_index)
            main_window['pl_move_up'].update(disabled=not pl_tracks)
            main_window['pl_move_down'].update(disabled=not pl_tracks)
            main_window['pl_rm_items'].update(disabled=not pl_tracks)
    elif main_event == 'pl_add_tracks':
        initial_folder = settings['last_folder'] if settings['use_last_folder'] else DEFAULT_FOLDER
        file_paths = Sg.popup_get_file('Select Music File(s)', no_window=True, initial_folder=initial_folder,
                                       multiple_files=True, file_types=AUDIO_FILE_TYPES, icon=WINDOW_ICON)
        if file_paths:
            pl_tracks.extend(get_audio_uris(file_paths))
            settings['last_folder'] = os.path.dirname(file_paths[-1])
            main_window.TKroot.focus_force()
            main_window.normal()
            formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
            new_i = len(formatted_tracks) - 1
            main_window['pl_tracks'].update(formatted_tracks, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
            main_window['pl_move_up'].update(disabled=new_i == 0)
            main_window['pl_move_down'].update(disabled=True)
            main_window['pl_rm_items'].update(disabled=not pl_tracks)
    elif main_event == 'pl_url_input':
        # disable or enable add URL button if the text in the URL input is almost a valid link
        link = main_values['pl_url_input']
        valid_link = link.count('.') and (link.startswith('http://') or link.startswith('https://'))
        main_window['pl_add_url'].update(disabled=not valid_link)
    elif main_event == 'pl_add_url':
        link = main_values['pl_url_input']
        if link.startswith('http://') or link.startswith('https://'):
            uris_to_scan.put(link)
            pl_tracks.append(link)
            formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
            new_i = len(formatted_tracks) - 1
            main_window['pl_tracks'].update(formatted_tracks, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
            main_window['pl_rm_items'].update(disabled=False)
            main_window['pl_move_up'].update(disabled=len(formatted_tracks) == 1)
            main_window['pl_move_down'].update(disabled=True)
            # empty the input field
            main_window['pl_url_input'].update(value='')
            main_window['pl_add_url'].update(disabled=True)
            main_window['pl_url_input'].set_focus()
        else:
            tray_notify(gt('ERROR') + ': ' + gt("Invalid URL. URL's need to start with http:// or https://"))
    elif main_event == 'pl_tracks':
        pl_items = main_window['pl_tracks'].get_list_values()
        main_window['pl_move_up'].update(disabled=len(main_value) != 1 or pl_items[0] == main_value[0])
        main_window['pl_move_down'].update(disabled=len(main_value) != 1 or pl_items[-1] == main_value[0])
        main_window['pl_rm_items'].update(disabled=not main_value)
    elif main_event == 'pl_move_up':
        # only allow moving up if 1 item is selected and pl_files is not empty
        if len(main_values['pl_tracks']) == 1 and pl_tracks:
            to_move = main_window['pl_tracks'].get_indexes()[0]
            if to_move:
                new_i = to_move - 1
                pl_tracks.insert(new_i, pl_tracks.pop(to_move))
                formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
                main_window['pl_tracks'].update(values=formatted_tracks, set_to_index=new_i,
                                                scroll_to_index=max(new_i - 3, 0))
                main_window['pl_move_up'].update(disabled=new_i == 0)
                main_window['pl_move_down'].update(disabled=False)
        else:
            main_window['pl_move_up'].update(disabled=True)
            main_window['pl_move_down'].update(disabled=True)
    elif main_event == 'pl_move_down':
        # only allow moving down if 1 item is selected and pl_files is not empty
        if len(main_values['pl_tracks']) == 1 and pl_tracks:
            to_move = main_window['pl_tracks'].get_indexes()[0]
            if to_move < len(pl_tracks) - 1:
                new_i = to_move + 1
                pl_tracks.insert(new_i, pl_tracks.pop(to_move))
                formatted_tracks = [f'{i + 1}. {format_uri(path)}' for i, path in enumerate(pl_tracks)]
                main_window['pl_tracks'].update(values=formatted_tracks, set_to_index=new_i,
                                                scroll_to_index=max(new_i - 3, 0))
                main_window['pl_move_up'].update(disabled=False)
                main_window['pl_move_down'].update(disabled=new_i == len(pl_tracks) - 1)
        else:
            main_window['pl_move_up'].update(disabled=True)
            main_window['pl_move_down'].update(disabled=True)
    elif main_event == 'pl_locate_track':
        for i in main_window['pl_tracks'].get_indexes():
            locate_uri(uri=pl_tracks[i])
    # other GUI updates
    if time.time() - progress_bar_last_update > 0.5:
        # update progress bar every 0.5 seconds
        progress_bar: Sg.Slider = main_window['progress_bar']
        if playing_status.stopped():
            progress_bar.update(0, disabled=True)
        elif music_queue:
            get_track_position()
            progress_bar.update(track_position, range=(0, track_length), disabled=False)
            update_progress_bar_text = True
            progress_bar_last_update = time.time()
        elif not sar.alive:
            playing_status.stop()
    if update_progress_bar_text:
        elapsed_time_text, time_left_text = create_progress_bar_text(track_position, track_length)
        main_window['time_elapsed'].update(elapsed_time_text)
        main_window['time_left'].update(time_left_text)
    p_r_button = main_window['pause/resume']
    if playing_status.playing() and p_r_button.metadata != playing_status:
        p_r_button.update(image_data=PAUSE_BUTTON_IMG)
    elif playing_status.paused() and p_r_button.metadata != playing_status:
        p_r_button.update(image_data=PLAY_BUTTON_IMG)
    elif playing_status.stopped() and p_r_button.metadata != playing_status:
        p_r_button.update(image_data=PLAY_BUTTON_IMG)
        main_window['time_elapsed'].update('0:00')
        main_window['time_left'].update('0:00')
    p_r_button.metadata = str(playing_status)
    return True


def create_shortcut():
    """
    Creates short-cut in Startup folder (enter "startup" in Explorer address bar to)
        if setting['run_on_startup'], else removes existing shortcut
    """
    def _create_shortcut():
        app_log.info('create_shortcut called')
        startup_dir = shell.SHGetFolderPath(0, (shellcon.CSIDL_STARTUP, shellcon.CSIDL_COMMON_STARTUP)[0], None, 0)
        debug = settings.get('DEBUG', DEBUG)
        shortcut_path = f"{startup_dir}\\Music Caster{' (DEBUG)' if debug else ''}.lnk"
        with suppress(com_error):
            shortcut_exists = os.path.exists(shortcut_path)
            if settings['run_on_startup'] and not shortcut_exists:
                # noinspection PyUnresolvedReferences
                pythoncom.CoInitialize()
                _shell = win32com.client.Dispatch('WScript.Shell')
                shortcut = _shell.CreateShortCut(shortcut_path)
                if IS_FROZEN:
                    target = f'{working_dir}\\Music Caster.exe'
                else:
                    target = f'{working_dir}\\music_caster.bat'
                    if os.path.exists(target):
                        with open('music_caster.bat', 'w') as f:
                            f.write(f'pythonw {os.path.basename(sys.argv[0])}')
                    shortcut.IconLocation = f'{working_dir}\\resources\\Music Caster Icon.ico'
                shortcut.Targetpath = target
                shortcut.WorkingDirectory = working_dir
                shortcut.WindowStyle = 1  # 7 - Minimized, 3 - Maximized, 1 - Normal
                shortcut.save()
                if debug: os.remove(shortcut_path)
            elif (not settings['run_on_startup'] or debug) and shortcut_exists: os.remove(shortcut_path)
    Thread(target=_create_shortcut, name='CreateShortcut').start()


def get_latest_release(ver, force=False):
    """
    returns {'version': latest_ver, 'setup': 'setup_link'}
        if the latest release verison is newer (>) than VERSION
    if latest release version <= VERSION, returns false
    if force: return latest release even if latest version <= VERSION
    """
    releases_url = 'https://api.github.com/repos/elibroftw/music-caster/releases/latest'
    release = requests.get(releases_url).json()
    latest_ver = release.get('tag_name', f'v{VERSION}')[1:]
    _version = [int(x) for x in ver.split('.')]
    compare_ver = [int(x) for x in latest_ver.split('.')]
    if compare_ver > _version or force:
        for asset in release.get('assets', []):
            # check if setup exists
            if 'exe' in asset['name']:
                return {'version': latest_ver, 'setup': asset['browser_download_url']}
    return False


def auto_update(auto_start=True):
    """
    auto_start should be True when checking for updates at startup up,
        false when checking for updates before exiting
    :return
    """
    with suppress(requests.RequestException):
        app_log.info(f'Function called: auto_update(auto_start={auto_start})')
        release = get_latest_release(VERSION, force=(not IS_FROZEN or settings.get('DEBUG', DEBUG)))
        if release:
            latest_ver = release['version']
            setup_dl_link = release['setup']
            app_log.info(f'Update found: v{latest_ver}')
            print('Installer Link:', setup_dl_link)
            if settings.get('DEBUG', DEBUG) or not setup_dl_link: return
            if IS_FROZEN:
                if os.path.exists(UNINSTALLER):
                    # only show message on startup to not confuse the user
                    cmd = 'mc_installer.exe /VERYSILENT /FORCECLOSEAPPLICATIONS /MERGETASKS="!desktopicon"'
                    if auto_start:
                        cmd_args = ' '.join(sys.argv[1:])
                        cmd += f' && "Music Caster.exe" {cmd_args}'  # auto start is True when updating on startup
                        download_update = gt('Downloading update $VER').replace('$VER', latest_ver)
                        tray_notify(download_update)
                        tray_tooltip = download_update
                        tray_process_queue.put({'method': 'update', 'kwargs': {'tooltip': tray_tooltip}})
                    try:
                        # download setup, close tray, run setup, and exit
                        download(setup_dl_link, 'mc_installer.exe')
                        if auto_start:
                            tray_process_queue.put({'method': 'close'})
                        Popen(cmd, shell=True)
                        sys.exit()
                    except OSError as _e:
                        if _e.errno == errno.ENOSPC:
                            if auto_start:
                                tray_notify(gt('ERROR') + ': ' + gt('No space left on device to auto-update'))
                    except (ConnectionAbortedError, ProtocolError):
                        if auto_start:
                            tray_notify('update_available', context=latest_ver)
                elif os.path.exists('Updater.exe'):
                    # portable installation
                    try:
                        os.startfile('Updater.exe')
                        sys.exit()
                    except OSError as _e:
                        if _e == errno.ECANCELED:
                            # user cancelled update, don't try auto-updating again
                            # inform user what we were trying to do though
                            change_settings('auto_update', False)
                            if auto_start and settings['notifications']:
                                tray_notify('update_available', context=latest_ver)
                else:
                    # unins000.exe or updater.exe was deleted
                    # Better to inform user there is an update available
                    if auto_start and settings['notifications']: tray_notify('update_available', context=latest_ver)


def send_info():
    with suppress(requests.RequestException):
        mac = hashlib.md5(get_mac().encode()).hexdigest()
        requests.post('https://en3ay96poz86qa9.m.pipedream.net', json={'MAC': mac, 'VERSION': VERSION})


def handle_action(action):
    actions = {
        '__ACTIVATED__': activate_main_window,
        # from tray menu
        gt('Rescan Library'): index_all_tracks,
        gt('Refresh Devices'): lambda: start_chromecast_discovery(start_thread=True),
        # isdigit should be an if statement
        gt('Settings'): lambda: activate_main_window('tab_settings'),
        gt('Playlists Menu'): lambda: activate_main_window('tab_playlists'),
        # PL should be an if statement
        gt('Set Timer'): lambda: activate_main_window('tab_timer'),
        gt('Cancel Timer'): cancel_timer,
        gt('System Audio'): play_system_audio,
        gt('Play URL'): lambda: activate_main_window('tab_url', 'url_play'),
        gt('Queue URL'): lambda: activate_main_window('tab_url', 'url_queue'),
        gt('Play URL Next'): lambda: activate_main_window('tab_url', 'url_play_next'),
        gt('Play File(s)'): file_action,
        gt('Queue File(s)'): lambda: file_action('qf'),
        gt('Play File(s) Next'): lambda: file_action('pfn'),
        gt('Play All'): play_all,
        gt('Pause'): pause,
        gt('Resume'): resume,
        gt('next track', 1): next_track,
        gt('previous track', 1): prev_track,
        gt('Stop'): lambda: stop('tray'),
        gt('Repeat One'): lambda: change_settings('repeat', True),
        gt('Repeat All'): lambda: change_settings('repeat', False),
        gt('Repeat Off'): lambda: change_settings('repeat', None),
        gt('locate track', 1): locate_uri,
        gt('Exit'): exit_program
    }
    actions.get(action, lambda: other_tray_actions(action))()


if __name__ == '__main__':
    log_format = logging.Formatter('%(asctime)s %(levelname)s (%(lineno)d): %(message)s')
    log_handler = RotatingFileHandler('music_caster.log', maxBytes=5242880, backupCount=1, encoding='UTF-8')
    log_handler.setFormatter(log_format)
    app_log = logging.getLogger('music_caster')
    app_log.setLevel(logging.INFO)
    app_log.addHandler(log_handler)
    app_log.propagate = False  # disable console output
    try:
        load_settings(True)  # starts indexing all tracks
        if settings['notifications']:
            if settings['update_message'] == '': tray_notify(WELCOME_MSG)
            elif settings['update_message'] != UPDATE_MESSAGE: tray_notify(UPDATE_MESSAGE)
        change_settings('update_message', UPDATE_MESSAGE)
        # check for update and update if no starting arguments were supplied or if the update flag was used
        if len(sys.argv) == 1 and settings['auto_update'] or args.update: auto_update()
        # set file handlers only if installed from the setup (Not a portable installation)
        if os.path.exists(UNINSTALLER):
            add_reg_handlers(f'{working_dir}/Music Caster.exe', add_folder_context=settings['folder_context_menu'])

        with suppress(FileNotFoundError, OSError): os.remove('mc_installer.exe')
        rmtree('Update', ignore_errors=True)

        # find a port to bind to
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            while True:
                if not s.connect_ex(('127.0.0.1', Shared.PORT)) == 0:  # if port is not occupied
                    with suppress(OSError):
                        # try to start server and bind it to PORT
                        server_kwargs = {'host': '0.0.0.0', 'port': Shared.PORT, 'threaded': True}
                        Thread(target=app.run, name='FlaskServer', daemon=True, kwargs=server_kwargs).start()
                        break
                Shared.PORT += 1  # port in use or failed to bind to port
        print(f'Running on http://127.0.0.1:{Shared.PORT}/')
        rich_presence = pypresence.Presence(MUSIC_CASTER_DISCORD_ID)
        if settings['discord_rpc']:
            with suppress(Exception): rich_presence.connect()
        temp = (settings['timer_shut_down'], settings['timer_hibernate'], settings['timer_sleep'])
        if temp.count(True) > 1:  # Only one of the below can be True
            if settings['timer_shut_down']: change_settings('timer_hibernate', False)
            change_settings('timer_sleep', False)
        if settings['persistent_queue'] and settings['populate_queue_startup']:  # mutually exclusive
            change_settings('populate_queue_startup', False)
        cast_last_checked = time.time()
        Thread(target=background_tasks, daemon=True, name='BackgroundTasks').start()
        start_chromecast_discovery(start_thread=True)
        audio_player = AudioPlayer()
        if args.uris:
            # wait until previous device has been found or if it hasn't been found
            ydl.add_default_info_extractors()
            while all((settings['previous_device'], cast is None, stop_discovery)): time.sleep(0.3)
            play_uris(args.uris, queue_uris=args.queue, play_next=args.playnext)
        elif settings['persistent_queue']:
            # load saved queues from settings.json
            for queue_name in ('done', 'music', 'next'):
                queue = {'done': done_queue, 'music': music_queue, 'next': next_queue}[queue_name]
                for file_or_url in settings['queues'].get(queue_name, []):
                    if valid_audio_file(file_or_url) or file_or_url.startswith('http'):
                        queue.append(file_or_url)
                        uris_to_scan.put(file_or_url)
        elif settings['populate_queue_startup']:
            try:
                indexing_tracks_thread.join()
                play_all(queue_only=True)
            except AttributeError:
                tray_notify(gt('ERROR') + ':' + gt('Could not populate queue because library scan is disabled'))
        while True:
            while not daemon_commands.empty():
                daemon_command = daemon_commands.get()  # pops oldest item
                try:
                    handle_action(daemon_command)
                except AttributeError:  # daemon_command (tray_item) is None
                    # in the future, tray_item gets put into daemon_commands
                    exit_program()
            if active_windows['main']:
                read_main_window()
            else:
                time.sleep(0.2)
    except Exception as e:
        # try to auto-update before exiting
        auto_update()
        handle_exception(e, True)