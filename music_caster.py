VERSION = latest_version = '4.68.0'
UPDATE_MESSAGE = """
[New] Queue all button
[New] Show track number
""".strip()
if __name__ != '__main__': raise RuntimeError(VERSION)  # hack
import argparse
parser = argparse.ArgumentParser(description='Music Caster')
parser.add_argument('--debug', '-d', default=False, action='store_true', help='allows > 1 instance + no info sent')
parser.add_argument('--queue', '-q', default=False, action='store_true', help='supplied paths are queued')
parser.add_argument('--update', '-u', default=False, action='store_true', help='allow updating')
parser.add_argument('--exit', '-x', default=False, action='store_true',
                    help='exits any existing instance (including self)')
parser.add_argument('paths', nargs='*', default=[], help='list of files/dirs/playlists to play/queue')
args = parser.parse_args()
# helper files
from helpers import *
from audio_player import AudioPlayer
import base64
from contextlib import suppress
from datetime import datetime, timedelta
# noinspection PyUnresolvedReferences
import encodings.idna  # DO NOT REMOVE
from functools import cmp_to_key
import glob
import io
import json
from json import JSONDecodeError
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import pprint
from random import shuffle
from shutil import copyfileobj, rmtree
import sys
from threading import Thread
from win32com.universal import com_error
import traceback
import urllib.parse
from urllib.parse import urlsplit
import webbrowser  # takes 0.05 seconds
import zipfile
# 3rd party imports
from flask import Flask, jsonify, render_template, request, redirect, send_file, Response
import PySimpleGUIWx as SgWx
import pyaudio
import wx
# import wx.lib.agw.multidirdialog as mdd
import pychromecast.controllers.media
from pychromecast.error import UnsupportedNamespace, NotConnected
from pychromecast.config import APP_MEDIA_RECEIVER
import pynput.keyboard
import pyperclip
import pypresence
from pypresence import PyPresenceException
import threading
import pythoncom
from PIL import UnidentifiedImageError
import requests
import win32com.client
import winshell
from youtube_dl import YoutubeDL

# CONSTANTS
MUSIC_FILE_TYPES = 'Audio File (.mp3, .mp4, .mpeg, .m4a, .flac, .aac, .ogg, .opus, .wma, .wav)|' \
                   '*.mp3;*.mp4;*.mpeg;*.m4a;*.flac;*.aac;*.ogg;*.opus;*.wma;*.wav'
DEBUG = args.debug
starting_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(starting_dir)
EMAIL = 'elijahllopezz@gmail.com'
EMAIL_URL = f'mailto:{EMAIL}?subject=Regarding%20Music%20Caster%20v{VERSION}'
MUSIC_CASTER_DISCORD_ID = '696092874902863932'
UNINSTALLER = 'unins000.exe'
PORT, WAIT_TIMEOUT, IS_FROZEN = 2001, 10, getattr(sys, 'frozen', False)
STREAM_CHUNK = 1024
PRESSED_KEYS = set()
show_pygame_error = update_devices = settings_file_in_use = False
update_available = exit_flag = False
last_play_command = 0  # last call to /play/
settings_last_modified, last_press = 0, time.time() + 5
update_last_checked = time.time()  # check every hour
active_windows = {'main': False, 'playlist_selector': False,
                  'playlist_editor': False, 'play_url': False}
main_window = timer_window = pl_editor_window = pl_selector_window = play_url_window = Sg.Window('')
main_last_event = pl_editor_last_event = None
py_presence_errors = (AttributeError, RuntimeError, PermissionError, UnicodeDecodeError,
                      PyPresenceException, JSONDecodeError)
# noinspection PyTypeChecker
cast: pychromecast.Chromecast = None
playlists, all_tracks, url_metadata = {}, {}, {}
# playlist_name: [], formatted_name: file path, file: {artist: str, title: str}
tray_playlists, tray_folders = ['Create/Edit a Playlist'], []
all_folders, pl_name = ['PF: Select Folder(s)'], ''
pl_files = []  # keep track of paths when editing playlists
chromecasts, device_names = [], ['✓ Local device']
music_directories, window_locations = [], {}
music_queue, done_queue, next_queue = [], [], []
update_lb_queue = False
mouse_hover = ''
daemon_command = ''
playing_url = playing_live = False
live_lag = 0.0
progress_bar_last_update = track_position = timer = track_end = track_length = track_start = 0
# seconds but using time()
playing_status = 'NOT PLAYING'  # or PLAYING or PAUSED
# if music caster was launched in some other folder, play all or queue all that folder?
DEFAULT_DIR = home_music_dir = f'{Path.home()}/Music'
settings_file = f'{starting_dir}/settings.json'

DEFAULT_THEME = {'accent': '#00bfff', 'background': '#121212', 'text': '#d7d7d7'}
settings = {  # default settings
    'previous_device': None, 'window_locations': {}, 'update_message': '', 'EXPERIMENTAL': False,
    'auto_update': False, 'run_on_startup': True, 'notifications': True, 'shuffle_playlists': True, 'repeat': False,
    'discord_rpc': False, 'save_window_positions': True, 'populate_queue_startup': False, 'save_queue_sessions': False,
    'volume': 100, 'muted': False, 'volume_delta': 5, 'scrubbing_delta': 5, 'flip_main_window': False,
    'show_track_number': False, 'folder_cover_override': False, 'show_album_art': True, 'folder_context_menu': True,
    'vertical_gui': False, 'mini_mode': False, 'mini_on_top': True, 'update_check_hours': 1,
    'timer_shut_off_computer': False, 'timer_hibernate_computer': False, 'timer_sleep_computer': False,
    'theme': DEFAULT_THEME.copy(), 'file_format': '&artist - &title',
    'music_directories': [home_music_dir], 'playlists': {},
    'queues': {'done': [], 'music': [], 'next': []}}
# noinspection PyTypeChecker
indexing_tracks_thread: Thread = None
# noinspection PyTypeChecker
save_queue_thread: Thread = None
# noinspection PyTypeChecker
ydl: YoutubeDL = None
app = Flask(__name__)
app.jinja_env.lstrip_blocks = True
app.jinja_env.trim_blocks = True
logging.getLogger('werkzeug').disabled = True
os.environ['WERKZEUG_RUN_MAIN'] = 'true'
stop_discovery = lambda: None  # this is for the chromecast discover function


def save_settings():
    global settings, settings_file, settings_file_in_use
    if not settings_file_in_use:
        settings_file_in_use = True
        with open(settings_file, 'w') as outfile:
            json.dump(settings, outfile, indent=4)
        settings_file_in_use = False


def refresh_folders():
    tray_folders.clear()
    tray_folders.append('PF: Select Folder(s)')
    for music_dir in music_directories:
        music_dir = music_dir.replace('\\', '/').split('/')
        music_dir = f'PF: ../{"/".join(music_dir[-2:])}' if len(music_dir) > 2 else 'PF: ' + '/'.join(music_dir)
        tray_folders.append(music_dir)


def refresh_tray():
    refresh_folders()
    if playing_status == 'PLAYING': tray.update(menu=menu_def_2)
    elif playing_status == 'PAUSED': tray.update(menu=menu_def_3)
    else: tray.update(menu=menu_def_1)


def change_settings(settings_key, new_value):
    """ can be called from non-main thread """
    global settings, active_windows, tray
    if settings[settings_key] != new_value:
        settings[settings_key] = new_value
        save_settings()
        if settings_key == 'repeat':
            repeat_menu[0] = 'Repeat All ✓' if new_value is False else 'Repeat All'
            repeat_menu[1] = 'Repeat One ✓' if new_value else 'Repeat One'
            repeat_menu[2] = 'Repeat Off ✓' if new_value is None else 'Repeat Off'
            refresh_tray()
            if settings['notifications']:
                if new_value is None: tray.show_message('Music Caster', 'Repeat set to Off', time=5000)
                elif new_value: tray.show_message('Music Caster', 'Repeat set to One', time=5000)
                else: tray.show_message('Music Caster', 'Repeat set to All', time=5000)
    return new_value


def save_queues():
    global save_queue_thread, settings

    def _save_queue():
        settings['queues']['done'] = done_queue
        settings['queues']['music'] = music_queue
        settings['queues']['next'] = next_queue
        save_settings()

    if save_queue_thread is None or not save_queue_thread.is_alive():
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
    repeat_value = settings['repeat']
    repeat_button: Sg.Button = main_window['repeat']
    if repeat_value is None:
        repeat_img = REPEAT_OFF_IMG
        new_tooltip = 'Repeat'
    elif repeat_value:
        repeat_img = REPEAT_ONE_IMG
        new_tooltip = "Don't repeat"
    else:
        repeat_img = REPEAT_ALL_IMG
        new_tooltip = 'Repeat track'
    repeat_button.metadata = repeat_value
    repeat_button.update(image_data=repeat_img)
    repeat_button.set_tooltip(new_tooltip)


def cycle_repeat(update_main=False):
    """
    :param update_main: Only set to True on main Thread
    :return: repeat value
    """
    global settings
    if settings['repeat'] is None: new_repeat_setting = False  # Repeat All
    elif settings['repeat']: new_repeat_setting = None         # Repeat OFF
    else: new_repeat_setting = True                            # Repeat One
    if update_main and active_windows['main']: update_repeat_button()  # update main window if it is active
    return change_settings('repeat', new_repeat_setting)


def handle_exception(exception, restart_program=False):
    _current_time = str(datetime.now())
    trace_back_msg = traceback.format_exc()
    exc_type, exc_obj, exc_tb = sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2]
    mac = get_mac()
    if playing_url: playing_uri = 'url'
    elif playing_live: playing_uri = 'live'
    else: playing_uri = 'file' if music_queue else 'none'
    payload = {'VERSION': VERSION, 'EXCEPTION TYPE': exc_type.__name__, 'LINE': exc_tb.tb_lineno,
               'TRACEBACK': fix_path(trace_back_msg), 'MAC': mac, 'FATAL': restart_program,
               'OS': platform.platform(), 'TIME': _current_time, 'PLAYING_TYPE': playing_uri}
    try:
        with open(f'{starting_dir}/error.log', 'r') as _f:
            content = _f.read()
    except (FileNotFoundError, ValueError):
        content = ''
    with open(f'{starting_dir}/error.log', 'w') as _f:
        _f.write(pprint.pformat(payload))
        _f.write('\n')
        _f.write(content)
    if not IS_FROZEN: raise exception
    with suppress(requests.ConnectionError):
        requests.post('https://enmuvo35nwiw.x.pipedream.net', json=payload)
    if restart_program:
        with suppress(NameError):
            tray.show_message('Music Caster', 'An error occurred, restarting now', time=5000)
            time.sleep(5)
        with suppress(Exception):
            stop('error handling')
        if IS_FROZEN: os.startfile('Music Caster.exe')
        sys.exit()


def get_album_art(file_path: str) -> tuple:  # mime: str, data: str / (None, None)
    folder = os.path.dirname(file_path)
    png_cover = os.path.join(folder, 'cover.png')
    jpg_cover = os.path.join(folder, 'cover.jpg')
    jpeg_cover = os.path.join(folder, 'cover.jpeg')
    if settings['folder_cover_override']:
        for folder_cover in (png_cover, jpg_cover, jpeg_cover):
            if os.path.exists(folder_cover):
                data = io.BytesIO()
                im = Image.open(folder_cover)
                ext = folder_cover.rsplit('.', 1)
                im.save(data, format=ext, quality=95)
                return ext, base64.b64encode(data.getvalue())
    tags = mutagen.File(file_path)
    if tags is not None:
        for tag in tags.keys():
            if 'APIC' in tag:
                return tags[tag].mime, base64.b64encode(tags[tag].data).decode()  # 'utf-8'
    return None, None


def get_current_album_art():
    if playing_live: return LIVE_AUDIO_ART
    art = None
    if playing_status != 'NOT PLAYING' and music_queue:
        uri = music_queue[0]
        if uri.startswith('http'):
            if 'art_data' in url_metadata: return url_metadata['art_data']
            try:
                art_src = url_metadata[uri]['art']
                art_data = base64.b64encode(requests.get(art_src).content)
                url_metadata['art_data'] = art_data
                return art_data
            except KeyError: return DEFAULT_ART
        art = get_album_art(uri)[1] if playing_status in {'PLAYING', 'PAUSED'} else None
    return DEFAULT_ART if art is None else art


def get_metadata_wrapped(file_path: str) -> tuple:  # title, artist, album
    try:
        return get_metadata(file_path)
    except mutagen.MutagenError:
        try:
            metadata = all_tracks[file_path]
            return metadata['title'], metadata['artist'], metadata['album']
        except KeyError:
            return 'Unknown Title', 'Unknown Artist', 'Unknown Album'


def get_uri_metadata(uri):
    # get metadata from all_track and resort to url_metadata if not found in all_tracks
    #   if file/url is not in all_track. e.g. links
    uri = uri.replace('\\', '/')
    try: return all_tracks[uri]
    except KeyError:
        try:
            return url_metadata[uri]
        except KeyError:
            title, artist, album = get_metadata_wrapped(uri)
            if title == 'Unknown Title' or artist == 'Unknown Artist':
                sort_key = os.path.splitext(os.path.basename(uri))[0]
            else: sort_key = f'{title} - {artist}'
            metadata = {'title': title, 'artist': artist, 'album': album, 'sort_key': sort_key}
            try:
                length = get_length(uri)
                metadata['length'] = length
            except InvalidAudioFile:
                app_log.error(f'Could not get length for {uri}')
                tray.show_message('Music Caster', f'ERROR: is {uri} a valid audio file?')
            all_tracks[uri] = metadata
            return metadata


def get_current_metadata():
    if playing_live: return url_metadata['LIVE']
    elif music_queue: return get_uri_metadata(music_queue[0])
    else: return {'artist': 'N/A', 'title': 'Nothing Playing', 'album': 'N/A'}


def index_all_tracks(update_global=True, ignore_files: list = None):
    # returns the music library dict or starts building the library
    global indexing_tracks_thread, all_tracks
    if ignore_files is None: ignore_files = set()

    def _index_library():
        global all_tracks
        nonlocal  ignore_files
        use_temp = not not all_tracks
        all_tracks_temp = {}
        ignore_files = set(ignore_files)
        for directory in music_directories:
            for file_path in glob.iglob(f'{glob.escape(directory)}/**/*.*', recursive=True):
                file_path = file_path.replace('\\', '/')
                if file_path not in ignore_files and valid_music_file(file_path):
                    with suppress(HeaderNotFoundError):
                        title, artist, album = get_metadata_wrapped(file_path)
                        if title == 'Unknown Title' or artist == 'Unknown Artist':
                            sort_key = os.path.splitext(os.path.basename(file_path))[0]
                        else:
                            sort_key = f'{title} - {artist}'
                        metadata = {'title': title, 'artist': artist, 'album': album, 'sort_key': sort_key}
                        with suppress(KeyError, TypeError, MutagenError, IndexError):
                            track_number = get_track_number(file_path)[0].split('/', 1)[0]
                            metadata['track_number'] = track_number
                        if use_temp: all_tracks_temp[file_path] = metadata
                        else: all_tracks[file_path] = metadata
        if use_temp: all_tracks = all_tracks_temp.copy()
        del all_tracks_temp

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
            window_locations[_key] = window.CurrentLocation()
            save_settings()
    window.TKroot.bind('<Destroy>', save_window_position)


def get_window_location(window_key):
    if not settings['save_window_positions']: window_key = 'DEFAULT'
    return window_locations.get(window_key, (None, None))


def load_settings():  # up to 0.4 seconds
    """load (and fix if needed) the settings file"""
    global settings, playlists, music_directories, settings_last_modified, DEFAULT_DIR,\
        window_locations, settings_file_in_use
    if settings_file_in_use: return
    elif os.path.exists(settings_file):
        settings_file_in_use = True
        with open(settings_file) as json_file:
            try: loaded_settings = json.load(json_file)
            except json.decoder.JSONDecodeError: loaded_settings = {}
            _save_settings = False
            for setting_name, setting_value in tuple(loaded_settings.items()):
                loaded_settings[setting_name.replace(' ', '_')] = loaded_settings.pop(setting_name)
            for setting_name, setting_value in settings.items():
                if setting_name not in loaded_settings:
                    loaded_settings[setting_name] = setting_value
                    _save_settings = True
            settings = loaded_settings
            playlists = settings['playlists']
            tray_playlists.clear()  # global variable
            tray_playlists.append('Create/Edit a Playlist')
            tray_playlists.extend([f'PL: {pl}' for pl in playlists.keys()])
            _temp = music_directories.copy()
            music_directories = settings['music_directories']
            window_locations = settings['window_locations']
            if not music_directories: music_directories = change_settings('music_directories', [home_music_dir])
            if _temp != music_directories or music_directories == [home_music_dir]:
                index_all_tracks()
                refresh_folders()
            del _temp
            DEFAULT_DIR = music_directories[0]
            theme = settings['theme']
            for k, v in theme.copy().items():
                # validate settings file color codes
                if not valid_color_code(v):
                    _save_settings = True
                    theme[k] = DEFAULT_THEME[k]
            Sg.SetOptions(text_color=theme['text'], input_text_color=theme['text'], element_text_color=theme['text'],
                          background_color=theme['background'], text_element_background_color=theme['background'],
                          element_background_color=theme['background'], scrollbar_color=theme['background'],
                          input_elements_background_color=theme['background'], progress_meter_color=theme['accent'],
                          button_color=(theme['background'], theme['accent']),
                          border_width=1, slider_border_width=1, progress_meter_border_depth=0)
        settings_file_in_use = False
        if _save_settings: save_settings()
    else:
        save_settings()
        load_settings()
    settings_last_modified = os.path.getmtime(settings_file)


@app.errorhandler(404)
def page_not_found(_):
    return redirect('/')


# use socket io?
@app.route('/', methods=['GET', 'POST'])
def web_index():  # web GUI
    global music_queue, playing_status, all_tracks, daemon_command
    if request.method == 'POST':
        for k, v in active_windows.items():  # Opens up GUI
            if v:
                {'main': main_window,
                 'playlist_selector': pl_selector_window,
                 'playlist_editor': pl_editor_window,
                 'play_url': play_url_window}[k].bring_to_front()
                return 'true'
        daemon_command = '__ACTIVATED__'
        return 'Music Caster'
    if request.args:
        if 'play' in request.args:
            if not resume() and music_queue: play(music_queue[0])
            else: play_all()
        elif 'pause' in request.args: pause()  # resume == play
        elif 'next' in request.args: next_track()
        elif 'prev' in request.args: prev_track()
        elif 'repeat' in request.args: cycle_repeat()
        elif 'shuffle' in request.args:
            change_settings('shuffle', not settings['shuffle'])
        return redirect('/')
    metadata = get_current_metadata()
    art = get_current_album_art()
    if type(art) == bytes: art = art.decode()
    art = f'data:image/png;base64,{art}'
    repeat_option = settings['repeat']
    repeat_color = 'red' if settings['repeat'] is not None else ''
    shuffle_option = 'red' if settings['shuffle_playlists'] else ''
    # sort by the formatted title
    list_of_tracks = []
    sorted_tracks = sorted(all_tracks.items(), key=lambda item: item[1]['sort_key'].lower())
    for filename, data in sorted_tracks:
        filename = urllib.parse.urlencode({'path': filename})
        list_of_tracks.append({'title': data['sort_key'], 'href': f'/play?{filename}'})
    _queue = create_track_list()[0]
    device_index = 0
    for i, device_name in enumerate(device_names):
        if device_name.startswith('✓'):
            device_index = i
            break
    formatted_devices = ['Local Device'] + [cc.name for cc in chromecasts]
    return render_template('index.html', device_name=platform.node(), shuffle=shuffle_option, repeat_color=repeat_color,
                           metadata=metadata, main_button='pause' if playing_status == 'PLAYING' else 'play', art=art,
                           settings=settings, list_of_tracks=list_of_tracks, repeat_option=repeat_option, queue=_queue,
                           device_index=device_index, devices=formatted_devices)


@app.route('/play/', methods=['GET', 'POST'])
def play_file_page():
    global music_queue, playing_status, last_play_command
    request_args = request.args if request.method == 'GET' else request.form
    from_explorer = time.time() - last_play_command < 0.5
    queue_only = request_args.get('queue', 'false').lower() == 'true' or from_explorer
    # < 0.5 because that's how fast Windows would open each instance of MC
    last_play_command = time.time()
    if 'paths' in request_args: play_paths(request_args.getlist('paths'), queue_only=queue_only,
                                           from_explorer=from_explorer)
    return redirect('/') if request.method == 'GET' else 'true'


@app.route('/metadata/')
def api_get_metadata():
    try:
        file_path = music_queue[0].replace('\\', '/')
        metadata = all_tracks.get(file_path, url_metadata[file_path])
    except (IndexError, KeyError):
        metadata = {'artist': 'N/A', 'title': 'Nothing Playing', 'album': 'N/A'}
    return jsonify(metadata)


@app.route('/running/')
def api_running():
    return 'true'


@app.route('/exit/', methods=['GET', 'POST'])
def api_exit():
    global daemon_command
    daemon_command = 'Exit'
    return 'true'


@app.route('/change-setting/', methods=['POST'])
def change_settings_web():
    with suppress(KeyError):
        setting_key = request.json['setting_name']
        if setting_key in settings:
            change_settings(setting_key, request.json['value'])
        if setting_key == 'volume':
            update_volume(0 if settings['muted'] else settings['volume'])
        return 'true'
    return 'false'


@app.route('/refresh-devices/')
def refresh_devices_web():
    Thread(target=start_chromecast_discovery, daemon=True, name='CCDiscovery').start()
    return 'true'


@app.route('/change-device/', methods=['POST'])
def change_device_web():
    with suppress(KeyError):
        change_device(int(request.json['device_index']))
        return 'true'
    return 'false'


@app.route('/file/')
def get_file():
    if 'path' in request.args:
        file_path = request.args['path']
        if os.path.isfile(file_path) and valid_music_file(file_path):
            if request.args.get('thumbnail_only', False):
                mime_type, img_data = get_album_art(file_path)
                if mime_type is None: mime_type, img_data = 'image/png', DEFAULT_ART
                else: img_data = base64.b64decode(img_data)
                ext = mime_type.split('/')[1]
                return send_file(io.BytesIO(img_data), attachment_filename=f'cover.{ext}',
                                 mimetype=mime_type, as_attachment=True, cache_timeout=360000, conditional=True)
            return send_file(file_path, conditional=True, as_attachment=True, cache_timeout=360000)
    return '401'


@app.route('/files/')
def return_all_files():
    device_name = platform.node()
    html_resp = f'<!DOCTYPE html><title>Music Caster Files</title><h1>Music Files on {device_name}</h1><ul>\n'
    # sort by filename
    sorted_tracks = sorted(all_tracks.items(), key=lambda item: item[0].lower())
    for filename, metadata in sorted_tracks:
        query = urllib.parse.urlencode({'path': filename})
        html_resp += f'<li><a title="{filename}" class="track" href="/file?{query}">{filename}</a></li>\n'
    return html_resp + '</ul>'


def gen_header(sample_rate, bits_per_sample, channels):
    data_size = 2000 * 10 ** 6
    o = bytes('RIFF', 'ascii')  # 4 bytes Marks file as RIFF
    o += (data_size + 36).to_bytes(4, 'little')  # (4 bytes) File size in bytes excluding this and RIFF marker
    o += bytes('WAVE', 'ascii')  # 4 bytes File type
    o += bytes('fmt ', 'ascii')  # 4 bytes Format Chunk Marker
    o += (16).to_bytes(4, 'little')  # 4 bytes Length of above format data
    o += (1).to_bytes(2, 'little')  # 2 bytes Format type (1 - PCM)
    o += channels.to_bytes(2, 'little')  # 2 bytes
    o += sample_rate.to_bytes(4, 'little')  # 4 bytes
    o += (sample_rate * channels * bits_per_sample // 8).to_bytes(4, 'little')  # 4 bytes
    o += (channels * bits_per_sample // 8).to_bytes(2, 'little')  # 2 bytes
    o += bits_per_sample.to_bytes(2, 'little')  # 2 bytes
    o += bytes('data', 'ascii')  # 4 bytes Data Chunk Marker
    o += data_size.to_bytes(4, 'little')  # 4 bytes Data size in bytes
    return o


def create_stream(pa, sample_rate, channels, input_device_index, chunk=1024):
    _format = pyaudio.paInt16
    return pa.open(format=_format, channels=channels, as_loopback=True, rate=sample_rate, input=True,
                   input_device_index=input_device_index, frames_per_buffer=chunk)


@app.route('/live/')
def get_live_audio():
    # send system live audio to chromecast

    def system_sound():
        global live_lag
        # TODO: detect and send silence
        # live system sound generator
        p = pyaudio.PyAudio()
        _format = pyaudio.paInt16
        bits_per_sample = 16
        # get output device
        look_for_device = get_default_output_device()
        sample_rate, channels, device_index = get_output_device(p, look_for_device)
        stream = create_stream(p, sample_rate, channels, device_index, STREAM_CHUNK)
        last_sleep = 0  # doubles as a first_run
        while True:
            if last_sleep == 0:
                wav_header = gen_header(sample_rate, bits_per_sample, channels)
                data = wav_header + stream.read(STREAM_CHUNK)
                last_sleep = time.time()
            else:
                if live_lag > 0.3 and time.time() - last_sleep > 1:
                    # don't sleep consecutively
                    sleep_for = min(live_lag * 0.9, 0.3)
                    live_lag -= sleep_for
                    time.sleep(sleep_for)
                    last_sleep = time.time()
                temp_device = get_default_output_device()  # check if output device has changed
                if look_for_device != temp_device:
                    look_for_device = temp_device
                    stream.close()
                    stream = create_stream(p, *get_output_device(p, look_for_device), STREAM_CHUNK)
                data = stream.read(STREAM_CHUNK)  # gets the live system audio
            yield data
    return Response(system_sound())


@app.route('/live/thumbnail.png')
def live_thumbnail():
    return send_file(io.BytesIO(base64.b64decode(LIVE_AUDIO_ART)), attachment_filename=f'thumbnail.png',
                     mimetype='image/png', as_attachment=True, cache_timeout=360000, conditional=True)


@cmp_to_key
def chromecast_sorter(cc1: pychromecast.Chromecast, cc2: pychromecast.Chromecast):
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
    if str(chromecast.uuid) == previous_device and cast != chromecast: cast = chromecast
    if chromecast.uuid not in [_cc.uuid for _cc in chromecasts]:
        chromecasts.append(chromecast)
        # chromecasts.sort(key=lambda _cc: (_cc.device.model_name, type, _cc.name, _cc.uuid))
        chromecasts.sort(key=chromecast_sorter)
        device_names.clear()
        for _i, _cc in enumerate(['Local device'] + chromecasts):
            _cc: pychromecast.Chromecast
            device_name = _cc if _i == 0 else _cc.name
            if (previous_device is None and _i == 0) or (type(_cc) != str and str(_cc.uuid) == previous_device):
                device_names.append(f'✓ {device_name}')
            else: device_names.append(f'{_i + 1}. {device_name}')
        refresh_tray()


def start_chromecast_discovery():
    global stop_discovery
    if stop_discovery is not None: stop_discovery()
    chromecasts.clear()
    stop_discovery = pychromecast.get_chromecasts(blocking=False, callback=chromecast_callback)
    time.sleep(WAIT_TIMEOUT + 1)
    stop_discovery()
    stop_discovery = None
    if not device_names: device_names.append(f'✓ Local device')
    refresh_tray()


def change_device(selected_index):
    global cast, playing_status
    if selected_index == 0: new_device = None
    else:
        try: new_device = chromecasts[selected_index - 1]
        except IndexError: new_device = None
    device_names.clear()
    for device_index, cc in enumerate(['Local device'] + chromecasts):
        cc: pychromecast.Chromecast = cc if device_index == 0 else cc.name
        if device_index == selected_index: device_names.append(f'✓ {cc}')
        else: device_names.append(f'{device_index + 1}. {cc}')
    refresh_tray()
    if cast != new_device:
        current_pos = 0
        if cast is not None and cast.app_id == APP_MEDIA_RECEIVER and playing_status in {'PLAYING', 'PAUSED'}:
            mc = cast.media_controller
            with suppress(UnsupportedNamespace):
                mc.update_status()  # Switch device without playback loss
                current_pos = mc.status.adjusted_current_time
                if mc.is_playing or mc.is_paused: mc.stop()
            with suppress(NotConnected):
                cast.quit_app()
        elif cast is None and audio_player.is_busy(): current_pos = audio_player.stop()
        cast = new_device
        volume = 0 if settings['muted'] else settings['volume']
        change_settings('previous_device', None if cast is None else str(cast.uuid))
        with suppress(AttributeError): cast.wait(timeout=WAIT_TIMEOUT)
        update_volume(volume)
        if playing_status in {'PAUSED', 'PLAYING'}:
            do_autoplay = False if playing_status == 'PAUSED' else True
            if not playing_live: play(music_queue[0], position=current_pos, autoplay=do_autoplay, switching_device=True)
            elif not stream_live_audio(True): playing_status = 'NOT PLAYING'


def format_file(uri: str):
    try:
        metadata = get_uri_metadata(uri)
        artist, title = metadata['artist'], metadata['title']
        if artist.startswith('Unknown') or title.startswith('Unknown'): raise KeyError
        formatted = settings['file_format'].replace('&artist', artist).replace('&title', title)
        try: number = metadata['track_number']
        except KeyError: number = ''
        if '&trck' in formatted:
            formatted = formatted.replace('&trck', number)
        elif settings['show_track_number'] and number:
            formatted = f'[{number}] {formatted}'
        return formatted
    except (TypeError, KeyError):  # show something useful instead of Unknown - Unknown
        if uri.startswith('http'): return uri
        base = os.path.basename(uri)
        return os.path.splitext(base)[0]


def create_track_list():
    """:returns the formatted tracks queue, and the selected value (currently playing)"""
    tracks = []
    mq_start = len(next_queue) + 1
    selected_value = None
    # format: Index. Artists - Title
    for i, uri in enumerate(done_queue):
        formatted_track = format_file(uri)
        i = len(done_queue) - i
        formatted_item = f'-{i}. {formatted_track}'
        tracks.append(formatted_item)
    if music_queue:
        formatted_track = format_file(music_queue[0])
        formatted_item = f' {0}. {formatted_track}'
        tracks.append(formatted_item)
        selected_value = formatted_item
    for i, uri in enumerate(next_queue):
        formatted_track = format_file(uri)
        i += 1
        spacing = ' ' if i < 10 else ''
        formatted_item = f'{spacing}{i}. {formatted_track}'
        tracks.append(formatted_item)
    for i, uri in enumerate(music_queue[1:]):
        formatted_track = format_file(uri)
        i += mq_start
        spacing = ' ' if i < 10 else ''
        formatted_item = f'{spacing}{i}. {formatted_track}'
        tracks.append(formatted_item)
    return tracks, selected_value


def after_play(artists: str, title, autoplay, switching_device):
    global playing_status, cast_last_checked
    app_log.info(f'after_play: autoplay={autoplay}, switching_device={switching_device}')
    # artists is comma separated string
    playing_text = f"{artists.split(', ')[0]} - {title}"
    if autoplay:
        if settings['notifications'] and not switching_device and not active_windows['main']:
            tray.show_message('Music Caster', 'Playing: ' + playing_text, time=500)
        playing_status = 'PLAYING'
        tray.update(menu=menu_def_2, data_base64=FILLED_ICON, tooltip=playing_text)
    else: tray.update(menu=menu_def_3, data_base64=UNFILLED_ICON)
    cast_last_checked = time.time()
    if settings['save_queue_sessions']: save_queues()
    if settings['discord_rpc']:
        with suppress(py_presence_errors):
            rich_presence.update(state=f'By: {artists}', details=title, large_image='default',
                                 large_text='Listening', small_image='logo', small_text='Music Caster')


def stream_live_audio(switching_device=False):
    global track_position, track_start, track_end, track_length, playing_live, live_lag
    if cast is None:
        tray.show_message('Music Caster', 'ERROR: Not connected to a cast device', time=5000)
        playing_live = False
        return False
    else:
        url = f'http://{get_ipv4()}:{PORT}/live/'
        _volume = 0 if settings['muted'] else settings['volume'] / 100
        cast.wait(timeout=WAIT_TIMEOUT)
        try:
            cast.set_volume(_volume)
            mc = cast.media_controller
            if mc.status.player_is_playing or mc.status.player_is_paused:
                mc.stop()
                mc.block_until_active(WAIT_TIMEOUT)
            title = 'Live Audio'
            artist = platform.node()
            album = 'Music Caster'
            metadata = {'metadataType': 3, 'albumName': album, 'title': title, 'artist': artist}
            url_metadata['LIVE'] = {'artist': artist, 'title': title, 'album': album}
            # mc.play_media(f'{url}', 'audio/wav', metadata=metadata, thumb=f'{url}thumbnail.png', stream_type='LIVE')
            mc.play_media(f'{url}', 'audio/wav', metadata=metadata, thumb=f'{url}thumbnail.png')
            mc.block_until_active(WAIT_TIMEOUT)
            start_time = time.time()
            playing_live = True
            while not mc.status.player_is_playing:
                time.sleep(0.1)
                with suppress(UnsupportedNamespace): mc.update_status()
            mc.play()  # force chromecast device to start playing
            live_lag = time.time() - start_time
            track_length = 108800  # 3 hour default
            track_position = 0
            track_start = time.time() - track_position
            track_end = track_start + track_length
            after_play(artist, title, True, switching_device)
            return True
        except NotConnected:
            if internet_available(): tray.show_message('Music Caster', 'ERROR: No Internet Connection')
            else: tray.show_message('Music Caster', 'ERROR: Could not connect to Chromecast')
            return False


def play_url_generic(src, ext, title, artist, album, length, position=0,
                     thumbnail=None, autoplay=True, switching_device=False):
    global track_position, track_start, track_end, playing_url, track_length, progress_bar_last_update
    _metadata = {'metadataType': 3, 'albumName': album, 'title': title, 'artist': artist}
    cast.wait(timeout=WAIT_TIMEOUT)
    cast.set_volume(0 if settings['muted'] else settings['volume'] / 100)
    mc = cast.media_controller
    if mc.status.player_is_playing or mc.status.player_is_paused:
        mc.stop()
        mc.block_until_active(WAIT_TIMEOUT)
    mc.play_media(src, f'video/{ext}', metadata=_metadata, thumb=thumbnail,
                  current_time=position, autoplay=autoplay)
    mc.block_until_active(WAIT_TIMEOUT)
    start_time = time.time()
    while mc.status.player_state not in {'PLAYING', 'PAUSED'}:
        print('waiting for chromecast to start playing', title)
        time.sleep(0.2)
        if time.time() - start_time > 5: break  # show error?
    progress_bar_last_update = time.time()
    track_position = position
    track_length = length
    track_start = time.time() - track_position
    track_end = track_start + track_length
    playing_url = True
    after_play(artist, title, autoplay, switching_device)
    return True


def play_url(url, position=0, autoplay=True, switching_device=False):
    global cast, playing_url, playing_status, track_length, track_start, track_end, cast_last_checked
    if cast is None:
        tray.show_message('Music Caster', 'ERROR: Not connected to a cast device', time=5000)
        return False
    elif url.startswith('http') and valid_music_file(url):  # source url e.g. http://...radio.mp3
        ext = url[::-1].split('.', 1)[0][::-1]
        url_frags = urlsplit(url)
        title, artist, album = url_frags.path.split('/')[-1], url_frags.netloc, url_frags.path[1:]
        metadata = {'title': title, 'artist': artist, 'length': 108000, 'album': album, 'src': url}
        url_metadata[url.replace('\\', '/')] = metadata
        track_length = 108000  # 3 hour default
        return play_url_generic(url, ext, title, artist, album, track_length, position=position,
                                thumbnail=None, autoplay=autoplay, switching_device=switching_device)
    elif 'soundcloud.com' in url:
        if url not in url_metadata:
            r = ydl.extract_info(url, download=False)
            url = url.replace('\\', '/')
            url_metadata[url] = {'title': r['title'], 'artist': r['uploader'], 'album': 'Unknown Album',
                                 'length': r['duration'], 'art': r['thumbnail'], 'src': r['url'], 'ext': r['ext']}
        metadata = url_metadata[url]
        return play_url_generic(metadata['src'], metadata['ext'], metadata['title'], metadata['artist'],
                                metadata['album'], metadata['length'], position=position,
                                thumbnail=metadata['art'], autoplay=autoplay, switching_device=switching_device)
    elif parse_youtube_id(url) is not None:
        try:
            if url not in url_metadata:
                r = ydl.extract_info(url, download=False)
                formats = [_f for _f in r['formats'] if _f['acodec'] != 'none' and _f['vcodec'] != 'none']
                formats.sort(key=lambda _f: _f['width'])
                _f = formats[0]
                url = url.replace('\\', '/')
                url_metadata[url] = {'title': r['track'] or r['title'], 'artist': r['artist'] or r['uploader'],
                                     'album': r['album'], 'length': r['duration'], 'art': r['thumbnail'],
                                     'src': _f['url'], 'ext': _f['ext']}
            metadata = url_metadata[url]
            artist = metadata['artist']
            return play_url_generic(metadata['src'], metadata['ext'], metadata['title'], artist, metadata['album'],
                                    metadata['length'], position=position, thumbnail=metadata['art'],
                                    autoplay=autoplay, switching_device=switching_device)
        except StopIteration as _e:
            tray.show_message('Music Caster', 'ERROR: Could not play URL. Is MC up to date?', time=5000)
            if not IS_FROZEN: raise _e
    return False


def play(uri, position=0, autoplay=True, switching_device=False):
    global track_start, track_end, track_length, track_position, music_queue, progress_bar_last_update, playing_live,\
        cast_last_checked, playing_url
    while not os.path.exists(uri):
        if play_url(uri, position=position, autoplay=autoplay, switching_device=switching_device): return
        music_queue.remove(uri)
        if music_queue: uri = music_queue[0]
        else: return
        position = 0
    uri = uri.replace('\\', '/')
    playing_url = playing_live = False
    cleaned_uri = 'some_file.' + uri.split('.')[-1]  # clean uri for log
    app_log.info(f'play: {cleaned_uri}, position={position}, autoplay={autoplay}, switching_device={switching_device}')
    try:
        track_length = get_length(uri)
    except InvalidAudioFile:
        tray.show_message('Music Caster', f"ERROR: can't play {music_queue.pop(0)}")
        if music_queue: play(music_queue[0])
        return
    title, artist, album = get_metadata_wrapped(uri)
    # update metadata of track in case something changed
    try:
        all_tracks[uri] = {**all_tracks[uri], 'artist': artist, 'title': title,
                           'album': album, 'length': track_length}
    except KeyError:
        all_tracks[uri] = {'artist': artist, 'title': title, 'album': album, 'length': track_length}
    with suppress(KeyError, TypeError, MutagenError, IndexError):
        # update track number if it changed
        track_number = get_track_number(uri)[0].split('/', 1)[0]
        all_tracks[uri]['track_number'] = track_number
    _volume = 0 if settings['muted'] else settings['volume'] / 100
    if cast is None:  # play locally
        audio_player.play(uri, volume=_volume, start_playing=autoplay, start_from=position)
    else:
        try:
            url_args = urllib.parse.urlencode({'path': uri})
            url = f'http://{get_ipv4()}:{PORT}/file?{url_args}'
            with suppress(RuntimeError): cast.wait(timeout=WAIT_TIMEOUT)
            cast_last_checked = time.time() + 60  # make sure background_tasks doesn't interfere
            cast.set_volume(_volume)
            mc = cast.media_controller
            metadata = {'metadataType': 3, 'albumName': album, 'title': title, 'artist': artist}
            ext = uri.split('.')[-1]
            mc.play_media(url, f'audio/{ext}', current_time=position,
                          metadata=metadata, thumb=url+'&thumbnail_only=true', autoplay=autoplay)
            t1 = time.time()
            mc.block_until_active(WAIT_TIMEOUT + 1)
            if time.time() - t1 > WAIT_TIMEOUT:
                app_log.info('play: FAILED TO BLOCK UNTIL ACTIVE')
            start_time = time.time()
            while mc.status.player_state not in {'PLAYING', 'PAUSED'}:
                time.sleep(0.2)
                if time.time() - start_time > WAIT_TIMEOUT: break
            app_log.info(f'play: mc.status.player_state={mc.status.player_state}')
            progress_bar_last_update = time.time()
        except (pychromecast.error.NotConnected, OSError):
            tray.show_message('Music Caster', 'ERROR: Could not connect to Chromecast device', time=5000)
            with suppress(pychromecast.error.UnsupportedNamespace): stop('play')
            return
    track_position = position
    track_start = time.time() - track_position
    track_end = track_start + track_length
    after_play(artist, title, autoplay, switching_device)


def play_all(starting_files: list = None, queue_only=False):
    global playing_status, indexing_tracks_thread
    music_queue.clear()
    done_queue.clear()
    if starting_files is None: starting_files = []
    starting_files = [_f.replace('\\', '/') for _f in starting_files if valid_music_file(_f)]
    if indexing_tracks_thread is not None and indexing_tracks_thread.is_alive() and settings['notifications']:
        tray.show_message('Music Caster', 'Some files may be missing as music library is still being built')
    if starting_files: music_queue.extend(index_all_tracks(False, starting_files).keys())
    else: music_queue.extend(all_tracks.keys())
    if music_queue: shuffle(music_queue)
    if starting_files:
        for j, _f in enumerate(starting_files):
            music_queue.insert(j, _f)
    if not queue_only:
        if music_queue:
            play(music_queue[0])
        elif next_queue:
            playing_status = 'PLAYING'
            next_track()


def queue_all():
    global update_lb_queue
    temp_lst = list(index_all_tracks(update_global=False, ignore_files=music_queue).keys())
    shuffle(temp_lst)
    music_queue.extend(temp_lst)
    update_lb_queue = True


def play_paths(paths, queue_only=False, from_explorer=False):
    global playing_status, update_lb_queue
    """
    Appends all music files in the provided paths/names (folders, files, playlist names) to a temp list,
        which is shuffled if shuffled is enabled in settings, and then extends music_queue.
        Note: file/folder paths take precedence over playlist name
    If queue_only is false, the music queue and done queue are cleared,
        before files are added to the music_queue
    If from_explorer is true, then the whole music queue is shuffled (if setting enabled),
        except for the track that is currently playing
    """
    if len(paths) == 1 and os.path.isfile(paths[0]) and not from_explorer:
        return play_all(paths, queue_only=queue_only)
    if not queue_only:
        music_queue.clear()
        done_queue.clear()
    app_log.info(f'play_paths: len(paths) = {len(paths)}, queue_only = {queue_only}')
    temp_queue = []
    for path in paths:
        invalid_path = True
        if os.path.exists(path):
            path = path.rstrip('\\').rstrip('/')
            if os.path.isfile(path):
                invalid_path = False
                if valid_music_file(path): temp_queue.append(path)
            else:
                for _file in glob.iglob(f'{glob.escape(path)}/**/*.*', recursive=True):
                    if valid_music_file(_file):
                        invalid_path = False
                        temp_queue.append(_file)
        if invalid_path: temp_queue.extend(settings['playlists'].get(path, []))
    update_lb_queue = True
    if settings['shuffle_playlists']:
        # if from_explorer make temp_queue all files already in queue
        temp_queue = music_queue[1:] * from_explorer + temp_queue
        shuffle(temp_queue)
        # remove all but first track if from_explorer
        for i in range(1, len(music_queue) * from_explorer): del music_queue[i]
    music_queue.extend(temp_queue)
    if not queue_only:
        if music_queue: play(music_queue[0])
        elif next_queue:
            playing_status = 'PLAYING'
            next_track()


def file_action(action='Play File(s)'):
    # actions = 'Play File(s)', 'Play File(s) Next', 'Queue File(s)'
    global music_queue, next_queue, playing_status, main_last_event, update_lb_queue
    fd = wx.FileDialog(None, 'Select Music File(s)', defaultDir=DEFAULT_DIR, wildcard=MUSIC_FILE_TYPES,
                       style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
    if fd.ShowModal() != wx.ID_CANCEL:
        paths = fd.GetPaths()
        app_log.info(f'file_action(action={action}), len(lst) is {len(paths)}')
        update_lb_queue = True
        main_last_event = Sg.TIMEOUT_KEY
        if action == 'Play File(s)':
            music_queue.clear()
            done_queue.clear()
            music_queue += [_f for _f in fd.GetPaths() if valid_music_file(_f)]
            if music_queue: play(music_queue[0])
        elif action == 'Queue File(s)':
            _start_playing = not music_queue
            music_queue += [_f for _f in fd.GetPaths() if valid_music_file(_f)]
            if _start_playing and music_queue: play(music_queue[0])
        elif action == 'Play File(s) Next':
            next_queue += [_f for _f in fd.GetPaths() if valid_music_file(_f)]
            if playing_status == 'NOT PLAYING' and not music_queue and next_queue:
                if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: cast.wait(timeout=WAIT_TIMEOUT)
                playing_status = 'PLAYING'
                next_track()
        else: raise ValueError('Expected one of: "Play File(s)", "Play File(s) Next", or "Queue File(s)"')
    else: main_last_event = 'file_action'


def play_file():
    file_action()


def queue_file():
    # TODO: add to tray menu
    file_action('Queue File(s)')


def play_next():
    file_action('Play File(s) Next')


def folder_action(action='Play Folder'):
    global music_queue, next_queue, playing_status, main_last_event, update_lb_queue
    # actions: 'Play Folder', 'Play Folder Next', 'Queue Folder'
    # multi dir support code. Issues with it though
    # dlg = mdd.MultiDirDialog(None, title='Select Folders', defaultPath=DEFAULT_DIR, pos=wx.GetMousePosition(),
    #                          agwStyle=mdd.DD_MULTIPLE | mdd.DD_DIR_MUST_EXIST)
    # half_way = wx.GetMousePosition()[1] - dlg.GetSize()[1] // 2
    # dlg.SetPosition((dlg.GetPosition()[0], half_way))
    # dlg.SetSize(dlg.GetSize()[0] * 3, dlg.GetSize()[1])
    # issues with multi dir support: freezes any open windows, that's why I have to close them and then reopen
    # open_main = False
    # for window in active_windows:
    #     if active_windows[window]:
    #         active_windows[window] = False
    #         if window == 'main': open_main = True
    #         {'main': main_window, 'playlist_selector': pl_selector_window,
    #          'playlist_editor': pl_editor_window, 'play_url': play_url_window}[window].close()
    dlg = wx.DirDialog(None, 'Select Folder', DEFAULT_DIR, style=wx.DD_DIR_MUST_EXIST)
    if dlg.ShowModal() != wx.ID_CANCEL and os.path.exists(dlg.GetPath()):
        temp_queue = []
        # folder_paths = dlg.GetPaths()
        folder_paths = [dlg.GetPath()]
        for folder_path in folder_paths:
            # multi support
            # drive, rest = folder_path.split('\\', 1)
            # drive = drive.split('(')[-1][:-1]
            # folder_path = drive + '/' + rest
            if os.path.exists(folder_path):
                for _f in glob.iglob(f'{glob.escape(folder_path)}/**/*.*', recursive=True):
                    if valid_music_file(_f): temp_queue.append(_f)
        if settings['shuffle_playlists']: shuffle(temp_queue)
        else: temp_queue.sort(key=natural_key_file)
        app_log.info(f'folder_action: action={action}), len(lst) is {len(temp_queue)}')
        update_lb_queue = True
        main_last_event = Sg.TIMEOUT_KEY
        if action == 'Play Folder':
            music_queue.clear()
            done_queue.clear()
            music_queue += temp_queue
            if music_queue: play(music_queue[0])
        elif action == 'Play Folder Next':
            next_queue += temp_queue
            if playing_status == 'NOT PLAYING' and not music_queue and next_queue:
                if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: cast.wait(timeout=WAIT_TIMEOUT)
                playing_status = 'PLAYING'
                next_track()
        elif action == 'Queue Folder':
            start_playing = not music_queue
            music_queue += temp_queue
            if start_playing and music_queue: play(music_queue[0])
        else: raise ValueError('Expected one of: "Play Folder", "Play Folder Next", or "Queue Folder"')
        del temp_queue
    else: main_last_event = 'folder_action'
    # if open_main: activate_main_window()


def internet_available(host='8.8.8.8', port=53, timeout=3):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False


def get_track_position():
    global track_position
    if cast is not None:
        if internet_available():
            try:
                mc = cast.media_controller
                mc.update_status()
                track_position = mc.status.adjusted_current_time
            except (UnsupportedNamespace, NotConnected):
                track_position = time.time() - track_start
        else:
            track_position = time.time() - track_start
    elif playing_status in {'PLAYING', 'PAUSED'}:
        track_position = audio_player.get_pos()
    return track_position


def pause():
    """ can be called from a non-main thread """
    global tray, playing_status, track_position
    if playing_status == 'PLAYING':
        try:
            if cast is None:
                track_position = time.time() - track_start
                if audio_player.pause(): app_log.info('paused local audio player')
                else: app_log.info(f'could not pause local audio player')
            else:
                if internet_available():
                    mc = cast.media_controller
                    mc.update_status()
                    mc.pause()
                    while not mc.status.player_is_paused: time.sleep(0.1)
                    track_position = mc.status.adjusted_current_time
                    app_log.info('paused cast device')
            playing_status = 'PAUSED'
            if settings['discord_rpc'] and (music_queue or playing_live):
                metadata = url_metadata['LIVE'] if playing_live else get_uri_metadata(music_queue[0])
                title, artist = metadata['title'], metadata['artist']
                with suppress(py_presence_errors):
                    rich_presence.update(state=f'By: {artist}', details=title, large_image='default',
                                         large_text='Paused', small_image='logo', small_text='Music Caster')
        except UnsupportedNamespace: stop('pause')
        tray.update(menu=menu_def_3, data_base64=UNFILLED_ICON)
        return True
    return False


def resume():
    global tray, playing_status, track_end, track_position, track_start
    if playing_status == 'PAUSED':
        try:
            if cast is None:
                if audio_player.resume(): app_log.info('resumed playback')
                else: app_log.info('failed to resume')
            else:
                mc = cast.media_controller
                mc.update_status()
                mc.play()
                mc.block_until_active(WAIT_TIMEOUT)
                while not mc.status.player_state == 'PLAYING': time.sleep(0.1)
                track_position = mc.status.adjusted_current_time
            track_start = time.time() - track_position
            track_end = track_start + track_length
            playing_status = 'PLAYING'
            metadata = get_current_metadata()
            artist, title = metadata['artist'].split(', ')[0], metadata['title']
            if settings['discord_rpc']:
                with suppress(py_presence_errors):
                    rich_presence.update(state=f'By: {artist}', details=title, large_image='default',
                                         large_text='Playing', small_image='logo', small_text='Music Caster')
            tray.update(menu=menu_def_2, data_base64=FILLED_ICON)
        except (UnsupportedNamespace, NotConnected):
            if music_queue: play(music_queue[0], position=track_position)
        return True
    return False


def stop(stopped_from: str, stop_cast=True):
    """
    can be called from a non-main thread
    note: does not check if playing_status is not 'NOT PLAYING'
    """
    global playing_status, cast, track_position, playing_live, playing_url
    app_log.info(f'Stopped from {stopped_from}')
    playing_status = 'NOT PLAYING'
    playing_live = playing_url = False
    if settings['discord_rpc']:
        with suppress(py_presence_errors): rich_presence.clear()
    if cast is not None:
        if internet_available() and cast.app_id == APP_MEDIA_RECEIVER:
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
                if mc.is_playing(): playing_status = 'PLAYING'
                elif mc.is_paused(): playing_status = 'PAUSED'
                return
    else: audio_player.stop()
    track_position = 0
    if not exit_flag: tray.update(menu=menu_def_1, data_base64=UNFILLED_ICON, tooltip='Music Caster')


def next_track(from_timeout=False):
    global playing_status
    app_log.info(f'next_track(from_timeout={from_timeout})')
    if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: playing_status = 'NOT PLAYING'
    elif playing_status != 'NOT PLAYING' and not playing_live and (next_queue or music_queue):
        # if repeat all or repeat is off or empty queue or not manual next
        if not settings['repeat'] or not music_queue or not from_timeout:
            if settings['repeat']: change_settings('repeat', False)
            if music_queue: done_queue.append(music_queue.pop(0))
            if next_queue: music_queue.insert(0, next_queue.pop(0))
            # if queue is empty but repeat is all AND there are songs in the done_queue
            if not music_queue and settings['repeat'] is False and done_queue:
                music_queue.extend(done_queue)
                done_queue.clear()
        if music_queue: play(music_queue[0])
        else: stop('next track')  # repeat is off / no tracks in queue


def prev_track():
    global playing_status
    app_log.info('prev_track()')
    if playing_status != 'NOT PLAYING' and not playing_live:
        if cast is not None and cast.app_id != APP_MEDIA_RECEIVER: playing_status = 'NOT PLAYING'
        else:
            if done_queue:
                if settings['repeat']: change_settings('repeat', False)
                track = done_queue.pop()
                music_queue.insert(0, track)
                play(track)
            elif music_queue: play(music_queue[0])


def background_tasks():
    global cast, cast_last_checked, track_start, track_end, track_position, settings_last_modified,\
        update_last_checked, latest_version, exit_flag
    while not exit_flag:
        # SETTINGS_LAST_MODIFIED
        if os.path.getmtime(settings_file) != settings_last_modified: load_settings()  # last modified gets updated here
        refresh_tray()
        if cast is not None and time.time() - cast_last_checked > 5 and internet_available():
            with suppress(UnsupportedNamespace):
                if cast.app_id == APP_MEDIA_RECEIVER:
                    mc = cast.media_controller
                    mc.update_status()
                    is_playing, is_paused = mc.status.player_is_playing, mc.status.player_is_paused
                    is_stopped = mc.status.player_is_idle  # buffering is okay
                    if not is_stopped:
                        new_track_position = mc.status.adjusted_current_time
                        # handle scrubbing of music from the home app
                        track_start = time.time() - new_track_position
                        track_end = time.time() + track_length - new_track_position
                        track_position = new_track_position
                    if is_paused: pause()  # pause() checks if playing status equals 'PLAYING'
                    elif is_playing: resume()
                    elif is_stopped and playing_status != 'NOT PLAYING': stop('background tasks', False)
                    _volume = settings['volume']
                    cast_volume = round(cast.status.volume_level * 100, 1)
                    if _volume != cast_volume:
                        if cast_volume > 0.5 or cast_volume <= 0.5 and not settings['muted']:
                            # if volume was changed via Google Home App
                            _volume = change_settings('volume', cast_volume)
                            if _volume and settings['muted']: change_settings('muted', False)
                            if active_windows['main']:
                                if _volume and settings['muted']:
                                    main_window['mute'].update(image_data=VOLUME_IMG)
                                    main_window['mute'].set_tooltip('mute')
                                main_window['volume_slider'].update(_volume)
                elif playing_status in {'PAUSED', 'PLAYING'}: stop('background tasks; app not running')
            cast_last_checked = time.time()
        if time.time() - update_last_checked > 216000:
            # never show a notification for the same latest version
            release = get_latest_release(latest_version)
            if release:
                latest_version = release['version']
                tray.show_message('Music Caster', f'Update v{latest_version} is available')
            update_last_checked = time.time()
        time.sleep(5)


def on_press(key):
    global last_press, daemon_command
    key = str(key)
    PRESSED_KEYS.add(key)
    valid_shortcut = len(PRESSED_KEYS) == 4 and "'m'" in PRESSED_KEYS
    ctrl_clicked = 'Key.ctrl_l' in PRESSED_KEYS or 'Key.ctrl_r' in PRESSED_KEYS
    shift_clicked = 'Key.shift' in PRESSED_KEYS or 'Key.shift_r' in PRESSED_KEYS
    alt_clicked = 'Key.alt_l' in PRESSED_KEYS or 'Key.alt_r' in PRESSED_KEYS
    # Ctrl + Alt + Shift + M open up main window
    if valid_shortcut and ctrl_clicked and shift_clicked and alt_clicked: daemon_command = '__ACTIVATED__'
    if key not in {'<179>', '<176>', '<177>', '<178>'} or time.time() - last_press < 0.15: return
    if key == '<179>' and playing_status != 'NOT PLAYING':
        if not pause(): resume()
    elif key == '<176>' and playing_status != 'NOT PLAYING': next_track()
    elif key == '<177>' and playing_status != 'NOT PLAYING': prev_track()
    elif key == '<178>': stop('keyboard shortcut')
    last_press = time.time()


def on_release(key):
    with suppress(KeyError): PRESSED_KEYS.remove(str(key))


def activate_main_window(selected_tab='tab_queue'):
    global active_windows, main_window
    # selected_tab can be 'tab_queue', 'tab_settings', or 'tab_timer'
    if not active_windows['main']:
        active_windows['main'] = True
        lb_tracks, selected_value = create_track_list()
        mini_mode = settings['mini_mode']
        save_window_loc_key = 'main' + '_mini_mode' if mini_mode else ''
        window_location = get_window_location(save_window_loc_key)
        size = (125, 125) if mini_mode else (255, 255)
        album_art_data = resize_img(get_current_album_art(), settings['theme']['background'],
                                    size).decode() if settings['show_album_art'] else None
        try: qr_code = create_qr_code(PORT)
        except OSError: qr_code = None  # long time without internet
        if playing_status in {'PAUSED', 'PLAYING'} and (music_queue or playing_live):
            if playing_live:
                metadata = url_metadata['LIVE']
                position = track_length
            else:
                metadata = get_uri_metadata(music_queue[0])
                position = get_track_position()
            length, artist, title = track_length, metadata['artist'].split(', ')[0], metadata['title']
            main_gui_layout = create_main(lb_tracks, selected_value, playing_status, settings, VERSION, timer, title,
                                          artist, qr_code=qr_code, album_art_data=album_art_data, track_length=length,
                                          track_position=position)
        else:
            main_gui_layout = create_main(lb_tracks, selected_value, playing_status, settings, VERSION, timer,
                                          qr_code=qr_code, album_art_data=album_art_data)
        main_window = Sg.Window('Music Caster', main_gui_layout, grab_anywhere=mini_mode, no_titlebar=mini_mode,
                                icon=WINDOW_ICON, return_keyboard_events=True, finalize=True,  use_default_focus=False,
                                keep_on_top=mini_mode and settings['mini_on_top'], location=window_location)
        if not settings['mini_mode']:
            main_window['queue'].update(set_to_index=len(done_queue), scroll_to_index=len(done_queue))
            main_window['queue'].bind('<Enter>', '_mouse_enter')
            main_window['queue'].bind('<Leave>', '_mouse_leave')
        main_window['volume_slider'].bind('<Enter>', '_mouse_enter')
        main_window['volume_slider'].bind('<Leave>', '_mouse_leave')
        main_window['progress_bar'].bind('<Enter>', '_mouse_enter')
        main_window['progress_bar'].bind('<Leave>', '_mouse_leave')
        set_save_position_callback(main_window, save_window_loc_key)
    if not settings['mini_mode']:
        main_window[selected_tab].Select()
        if selected_tab == 'tab_timer': main_window['minutes'].set_focus()
    main_window.TKroot.focus_force()
    main_window.normal()


def create_edit_playlists():
    global active_windows, pl_selector_window
    if active_windows['playlist_editor']:
        pl_editor_window.TKroot.focus_force()
        pl_editor_window.normal()
        return
    elif not active_windows['playlist_selector']:
        active_windows['playlist_selector'] = True
        window_location = get_window_location('playlist_selector')
        pl_selector_window = Sg.Window('Playlist Selector', create_playlist_selector(settings), finalize=True,
                                       icon=WINDOW_ICON, return_keyboard_events=True, location=window_location)
        set_save_position_callback(pl_selector_window, 'playlist_selector')
    pl_selector_window.TKroot.focus_force()
    pl_selector_window.normal()


def activate_play_url(combo_value='Play Immediately'):
    # combo_values = ['Play Immediately', 'Queue', 'Play Next']
    global play_url_window
    if not active_windows['play_url']:
        clipboard_txt: str = pyperclip.paste()
        if not clipboard_txt.startswith('http'): clipboard_txt = ''
        play_url_layout = create_play_url(combo_value=combo_value, default_text=clipboard_txt)
        active_windows['play_url'] = True
        window_location = get_window_location('play_url')
        play_url_window = Sg.Window('Music Caster - Play URL', play_url_layout, icon=WINDOW_ICON,
                                    finalize=True, return_keyboard_events=True, location=window_location)
        set_save_position_callback(play_url_window, 'play_url')
    play_url_window.TKroot.focus_force()
    play_url_window.normal()
    play_url_window['url'].set_focus()


def cancel_timer():
    global timer
    timer = 0
    if settings['notifications']: tray.show_message('Music Caster', 'Timer stopped', time=5000)


def locate_file():
    if music_queue: Popen(f'explorer /select,"{fix_path(music_queue[0])}"')


def exit_program():
    global exit_flag
    exit_flag = True
    for window in active_windows:
        if active_windows[window]:
            active_windows[window] = False
            {'main': main_window, 'playlist_selector': pl_selector_window,
             'playlist_editor': pl_editor_window, 'play_url': play_url_window}[window].close()
    tray.hide()
    with suppress(UnsupportedNamespace):
        if cast is None: stop('exit program')
        elif cast is not None and cast.app_id == APP_MEDIA_RECEIVER: cast.quit_app()
    with suppress(py_presence_errors): rich_presence.close()
    if settings['auto_update']: auto_update(False)
    sys.exit()  # since auto_update might not sys.exit()


def play_playlist(playlist_name):
    if playlist_name in playlists:
        music_queue.clear()
        done_queue.clear()
        music_queue.extend(playlists.get(playlist_name, []))
        if music_queue:
            if settings['shuffle_playlists']: shuffle(music_queue)
            play(music_queue[0])


def other_daemon_actions(command_name):
    if command_name.startswith('Show Notification: '):
        title, msg = command_name[19:].split(', ', 1)
        tray.show_message(title, msg, time=5000)


def other_tray_actions(_tray_item):
    global cast, cast_last_checked, timer
    if _tray_item.split('.', 1)[0].isdigit():  # if user selected a different device
        with suppress(ValueError):
            change_device(device_names.index(tray_item))
    elif _tray_item.startswith('PL: '):  # playlist
        play_playlist(tray_item[4:])
    elif _tray_item.startswith('PF: '):  # play folder
        if tray_item == 'PF: Select Folder(s)': wx.CallAfter(folder_action)
        else:
            Thread(target=play_paths, name='PlayFolder', daemon=True,
                   args=[[music_directories[tray_folders.index(tray_item) - 1]]]).start()
    elif playing_status == 'PLAYING' and time.time() > track_end:
        next_track(from_timeout=time.time() > track_end)
    elif timer and time.time() > timer:
        stop('timer')
        timer = 0
        if settings['timer_shut_off_computer']:
            if platform.system() == 'Windows': os.system('shutdown /p /f')
            else: os.system('shutdown -h now')
        elif settings['timer_hibernate_computer']:
            if platform.system() == 'Windows': os.system(r'rundll32.exe powrprof.dll,SetSuspendState Hibernate')
        elif settings['timer_sleep_computer']:
            if platform.system() == 'Windows': os.system('rundll32.exe powrprof.dll,SetSuspendState 0,1,0')


def reset_mouse_hover():
    global mouse_hover
    mouse_hover = ''


def reset_progress():
    # NOTE: needs to be in main thread
    main_window['progress_bar'].update(value=0)
    main_window['time_elapsed'].update(value='0:00')
    main_window['time_left'].update(value='0:00')
    main_window.refresh()


def read_main_window():
    global main_last_event, mouse_hover, playing_status, track_position, progress_bar_last_update,\
        track_start, track_end, timer, main_window, pl_files, pl_editor_window, update_lb_queue
    # make if statements into dict mapping
    main_event, main_values = main_window.read(timeout=1)
    if (main_event in {None, 'Escape:27'} and main_last_event not in {'file_action', 'folder_action'}
            or main_values is None):
        active_windows['main'] = False
        main_window.close()
        return False
    main_value = main_values.get(main_event)
    if 'mouse_leave' not in main_event and 'mouse_enter' not in main_event and main_event != Sg.TIMEOUT_KEY:
        main_last_event = main_event
    p_r_button = main_window['pause/resume']
    gui_title = main_window['title'].DisplayText
    update_progress_bar_text, artist, title = False, '', 'Nothing Playing'
    if playing_status in {'PAUSED', 'PLAYING'} and (playing_live or music_queue):
        metadata = url_metadata['LIVE'] if playing_live else get_uri_metadata(music_queue[0])
        artist, title = metadata['artist'].split(', ', 1)[0], metadata['title']
        if settings['show_track_number']:
            with suppress(KeyError):
                track_number = metadata['track_number']
                title = f'{track_number}. {title}'
    if gui_title != title:  # usually if music stops playing or another track starts playing
        main_window['title'].update(value=title)
        main_window['artist'].update(value=artist)
        if settings['show_album_art']:
            size = (125, 125) if settings['mini_mode'] else (255, 255)
            try:
                album_art_data = resize_img(get_current_album_art(), settings['theme']['background'], size).decode()
            except (UnidentifiedImageError, OSError):
                album_art_data = resize_img(DEFAULT_ART, settings['theme']['background'], size).decode()
            main_window['album_art'].update(data=album_art_data)
        update_lb_queue = True
    elif update_lb_queue and not settings['mini_mode']:
        update_lb_queue = False
        dq_len = len(done_queue)
        lb_music_queue: Sg.Listbox = main_window['queue']
        lb_tracks = create_track_list()[0]
        lb_music_queue.update(values=lb_tracks, set_to_index=dq_len, scroll_to_index=dq_len)
    if settings['repeat'] != main_window['repeat'].metadata: update_repeat_button()  # if repeat settings do not match
    # handle events here
    if main_event.startswith('MouseWheel'):
        main_event = main_event.split(':', 1)[1]
        delta = {'Up': 5, 'Down': -5}.get(main_event, 0)
        if mouse_hover == 'progress_bar':
            if playing_status in {'PLAYING', 'PAUSED'}:
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
    if main_event in {'j', 'l'} and (settings['mini_mode'] or main_values['tab_group'] != 'tab_timer'):
        if playing_status in {'PLAYING', 'PAUSED'}:
            delta = {'j': -settings['scrubbing_delta'], 'l': settings['scrubbing_delta']}[main_event]
            get_track_position()
            new_position = min(max(track_position + delta, 0), track_length)
            main_window['progress_bar'].update(value=new_position)
            main_values['progress_bar'] = new_position
            main_event = 'progress_bar'
            main_window.refresh()
    if main_event == Sg.TIMEOUT_KEY: pass
    elif main_event == '1:49': main_window['tab_queue'].select()
    elif main_event == '2:50' or main_event == 'tab_group' and main_values['tab_group'] == 'tab_timer':
        main_window['tab_timer'].select()
        main_window['minutes'].set_focus()
    elif main_event == 'tab_group' and main_values['tab_group'] == 'tab_queue': main_window['file_action'].set_focus()
    elif main_event == '3:51': main_window['tab_settings'].select()
    elif main_event in {'progress_bar_mouse_enter', 'queue_mouse_enter', 'volume_slider_mouse_enter'}:
        if main_event in {'progress_bar_mouse_enter', 'volume_slider_mouse_enter'} and settings['mini_mode']:
            main_window.grab_any_where_off()
        mouse_hover = '_'.join(main_event.split('_')[:-2])
    elif main_event in {'progress_bar_mouse_leave', 'queue_mouse_leave', 'volume_slider_mouse_leave'}:
        if main_event in {'progress_bar_mouse_leave', 'volume_slider_mouse_leave'} and settings['mini_mode']:
            main_window.grab_any_where_on()
        mouse_hover = '' if main_event != 'volume_slider_mouse_leave' else mouse_hover
    elif main_event in {'locate_file', 'e:69'}:
        with suppress(IndexError):
            selected_file_index = int(main_values['queue'][0].split('.', 1)[0])
            if selected_file_index < 0:
                Popen(f'explorer /select,"{fix_path(done_queue[selected_file_index])}"')
            elif (selected_file_index == 0 or selected_file_index > len(next_queue)) and music_queue:
                Popen(f'explorer /select,"{fix_path(music_queue[selected_file_index])}"')
            elif 0 < selected_file_index <= len(next_queue):
                Popen(f'explorer /select,"{fix_path(next_queue[selected_file_index - 1])}"')
    elif main_event == 'pause/resume' or main_event == 'k' and main_values['tab_group'] != 'tab_timer':
        try: pause_resume[playing_status]()
        except KeyError:
            if music_queue: play(music_queue[0])
            else: play_all()
    elif main_event == 'next' and playing_status != 'NOT PLAYING':
        reset_progress()
        next_track()
    elif main_event == 'prev' and playing_status != 'NOT PLAYING':
        reset_progress()
        prev_track()
    elif main_event == 'shuffle': pass  # TODO: move from settings; shuffle affects play folder and play playlists
    elif main_event in {'repeat', 'r:82'}: cycle_repeat(True)
    elif ((main_event in {'volume_slider', 'a', 'd'} or main_event.isdigit())
          and (settings['mini_mode'] or main_values['tab_group'] == 'tab_queue')):
        # User scrubbed volume bar or pressed (while on Tab 1 or in mini mode)
        delta = 0
        if main_event.isdigit():
            new_volume = int(main_event) * 10
        else:
            if main_event == 'a': delta = -5
            elif main_event == 'd': delta = 5
            new_volume = main_values['volume_slider'] + delta
        change_settings('volume', new_volume)
        update_volume(new_volume)
    elif main_event in {'mute', 'm:77'}:  # toggle mute
        muted = change_settings('muted', not settings['muted'])
        if muted:
            main_window['mute'].update(image_data=VOLUME_MUTED_IMG)
            main_window['mute'].set_tooltip('unmute')
            update_volume(0)
        else:
            main_window['mute'].update(image_data=VOLUME_IMG)
            main_window['mute'].set_tooltip('mute')
            update_volume(settings['volume'])
    elif main_event in {'Up:38', 'Down:40', 'Prior:33', 'Next:34'}:
        # with suppress(AttributeError, IndexError, KeyError):
        if not settings['mini_mode'] and main_window.FindElementWithFocus() == main_window['queue']:
            move = {'Up:38': -1, 'Down:40': 1, 'Prior:33': -3, 'Next:34': 3}[main_event]
            new_i = main_window['queue'].get_list_values().index(main_values['queue'][0]) + move
            new_i = min(max(new_i, 0), len(music_queue) - 1)
            main_window['queue'].update(set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif main_event == 'queue' and main_value:
        selected_file_index = main_window['queue'].get_list_values().index(main_value[0])
        if done_queue and selected_file_index < len(done_queue):
            while next_queue:  # design decision to empty next queue
                music_queue.insert(1, next_queue.pop())
            for i in range(len(done_queue) - selected_file_index):
                music_queue.insert(0, done_queue.pop())
        else:
            for i in range(selected_file_index - len(done_queue)):
                if not music_queue: break
                done_queue.append(music_queue.pop(0))
                if next_queue:
                    music_queue.insert(0, next_queue.pop(0))
        if music_queue: play(music_queue[0])
        updated_list = create_track_list()[0]
        dq_len = len(done_queue)
        main_window['queue'].update(values=updated_list, set_to_index=dq_len, scroll_to_index=dq_len)
        reset_progress()
    elif main_event == 'move_up' and main_values['queue']:
        # index_to_move = int(main_values['queue'][0].split('.', 1)[0])
        index_to_move = main_window['queue'].get_list_values().index(main_values['queue'][0])
        new_i = index_to_move - 1
        dq_len = len(done_queue)
        nq_len = len(next_queue)
        if index_to_move < dq_len and new_i >= 0:  # move within dq
            done_queue.insert(new_i, done_queue.pop(index_to_move))
        elif index_to_move == dq_len and done_queue:  # move index -1 to 1
            if next_queue:
                next_queue.insert(1, done_queue.pop())
            else:
                music_queue.insert(1, done_queue.pop())
        elif index_to_move == dq_len + 1:  # move 1 to -1
            if next_queue:
                done_queue.append(next_queue.pop(0))
            else:
                done_queue.append(music_queue.pop(1))
        elif next_queue and index_to_move > dq_len and index_to_move - dq_len < nq_len:  # within next_queue
            nq_i = new_i - dq_len - 1
            next_queue.insert(nq_i, next_queue.pop(nq_i + 1))
        elif next_queue and index_to_move == dq_len + nq_len + 1:  # moving into next queue
            next_queue.insert(nq_len - 1, music_queue.pop(1))
        elif new_i >= 0:  # moving within mq
            mq_i = new_i - dq_len - nq_len
            music_queue.insert(mq_i, music_queue.pop(mq_i + 1))
        else: new_i = max(new_i, 0)
        updated_list = create_track_list()[0]
        main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 7, 0))
    elif main_event == 'move_down' and main_values['queue']:
        index_to_move = main_window['queue'].get_list_values().index(main_values['queue'][0])
        dq_len, nq_len, mq_len = len(done_queue), len(next_queue), len(music_queue)
        if index_to_move < dq_len + nq_len + mq_len - 1:
            new_i = index_to_move + 1
            if index_to_move == dq_len - 1:  # move index -1 to 1
                if next_queue:
                    next_queue.insert(0, done_queue.pop())
                else:
                    music_queue.insert(1, done_queue.pop())
            elif index_to_move < dq_len:  # move within dq
                done_queue.insert(new_i, done_queue.pop(index_to_move))
            elif index_to_move == dq_len:  # move 1 to -1
                if next_queue:
                    done_queue.append(next_queue.pop(0))
                else:
                    done_queue.append(music_queue.pop(1))
            elif next_queue and index_to_move == dq_len + nq_len:  # moving into music_queue
                music_queue.insert(2, next_queue.pop())
            elif index_to_move < dq_len + nq_len + 1:  # within next_queue
                nq_i = index_to_move - dq_len - 1
                next_queue.insert(nq_i, next_queue.pop(nq_i - 1))
            else:  # within music_queue
                mq_i = new_i - dq_len - nq_len
                music_queue.insert(mq_i, music_queue.pop(mq_i - 1))
            updated_list = create_track_list()[0]
            main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif main_event == 'remove' and main_values['queue']:
        index_to_remove = main_window['queue'].get_list_values().index(main_values['queue'][0])
        dq_len, nq_len, mq_len = len(done_queue), len(next_queue), len(music_queue)
        if index_to_remove < dq_len:
            done_queue.pop(index_to_remove)
        elif index_to_remove == dq_len:
            music_queue.pop(0)
            if music_queue: play(music_queue[0])
        elif index_to_remove <= nq_len + dq_len:
            next_queue.pop(index_to_remove - dq_len - 1)
        elif index_to_remove < nq_len + mq_len + dq_len:
            music_queue.pop(index_to_remove - dq_len - nq_len)
        updated_list = create_track_list()[0]
        new_i = min(len(updated_list), index_to_remove)
        main_window['queue'].update(values=updated_list, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif main_event == 'file_option': main_window['file_action'].update(text=main_values['file_option'])
    elif main_event == 'folder_option': main_window['folder_action'].update(text=main_values['folder_option'])
    elif main_event == 'file_action':
        Thread(target=file_action, name='FileAction', daemon=True,
               kwargs={'action': main_values['file_option']}).start()
    elif main_event == 'folder_action':
        wx.CallAfter(folder_action, action=main_values['folder_option'])
    elif main_event == 'play_playlist': play_playlist(main_values['playlists'])
    elif main_event == 'url_actions': activate_play_url()
    elif main_event == 'queue_all':
        already_queueing = False
        for thread in threading.enumerate():
            if thread.name == 'QueueAll' and thread.is_alive():
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
        if playing_status in {'PLAYING', 'PAUSED'}: stop('clear queue')
        music_queue.clear()
        next_queue.clear()
        done_queue.clear()
    elif main_event == 'save_queue':
        if not active_windows['playlist_editor']:
            if done_queue or music_queue or next_queue:
                pl_files = done_queue + ([music_queue[0]] if music_queue else []) + next_queue + music_queue[1:]
                pl_editor_layout = create_playlist_editor(settings, pl_files)
                window_location = get_window_location('playlist_editor')
                pl_editor_window = Sg.Window('Playlist Editor', pl_editor_layout, finalize=True, icon=WINDOW_ICON,
                                             return_keyboard_events=True, location=window_location)
                pl_editor_window.TKroot.focus_force()
                pl_editor_window.normal()
                set_save_position_callback(pl_editor_window, 'playlist_editor')
                if pl_name == '':
                    pl_editor_window['playlist_name'].set_focus()
                else:
                    pl_editor_window['tracks'].set_focus()
                    pl_editor_window['tracks'].update(set_to_index=0)
                active_windows['playlist_editor'] = True
    elif main_event == 'play_next':
        play_next()
        main_window.TKroot.focus_force()
    elif main_event == 'locate_file':
        Popen(f'explorer /select,"{fix_path(music_queue[0])}"')
    # elif main_event == 'library':  # TODO
    elif main_event == 'progress_bar':
        if playing_status == 'NOT PLAYING':
            main_window['progress_bar'].update(disabled=True, value=0)
            return
        else:
            new_position = main_values['progress_bar']
            track_position = new_position
            if cast is not None:
                cast.media_controller.seek(new_position)
                playing_status = 'PLAYING'
            else:
                audio_player.set_pos(new_position)
            update_progress_bar_text = True
            track_start = time.time() - track_position
            track_end = track_start + track_length
    # settings
    elif main_event == 'email': Thread(target=webbrowser.open, daemon=True, args=[EMAIL_URL]).start()
    elif main_event == 'web_gui':
        Thread(target=webbrowser.open, daemon=True, args=[f'http://{get_ipv4()}:{PORT}']).start()
    elif main_event in {'auto_update', 'notifications', 'discord_rpc', 'run_on_startup', 'folder_cover_override',
                        'folder_context_menu', 'shuffle_playlists', 'save_window_positions', 'populate_queue_startup',
                        'show_track_number', 'save_queue_sessions', 'flip_main_window', 'vertical_gui',
                        'show_album_art'}:
        change_settings(main_event, main_value)
        if main_event == 'run_on_startup': create_shortcut(SHORTCUT_PATH)
        elif main_event == 'save_queue_sessions':
            if main_value: save_queues()
            else: change_settings('queues', {'done': [], 'music': [], 'next': []})
            change_settings('populate_queue_startup', False)
            main_window['populate_queue_startup'].update(value=False)
        elif main_event in 'populate_queue_startup':
            main_window['save_queue_sessions'].update(value=False)
            change_settings('save_queue_sessions', False)
        elif main_event == 'discord_rpc':
            with suppress(py_presence_errors):
                if main_value and playing_status in {'PAUSED', 'PLAYING'}:
                    metadata = url_metadata['LIVE'] if playing_live else get_uri_metadata(music_queue[0])
                    artist, title = metadata['artist'].split(', ', 1)[0], metadata['title']
                    rich_presence.connect()
                    rich_presence.update(state=f'By: {artist}', details=title, large_image='default',
                                         large_text='Listening', small_image='logo', small_text='Music Caster')
                elif not main_value: rich_presence.clear()
        elif main_event in {'show_album_art', 'vertical_gui', 'flip_main_window'}:
            # re-render main GUI
            active_windows['main'] = False
            main_window.close()
            activate_main_window('tab_settings')
    elif main_event == 'remove_folder' and main_values['music_dirs']:
        selected_item = main_values['music_dirs'][0]
        if selected_item in music_directories:
            music_directories.remove(selected_item)
            main_window['music_dirs'].update(music_directories)
            refresh_tray()
            save_settings()
            index_all_tracks()
    elif main_event == 'add_folder':
        main_value = main_value.replace('\\', '/')  # sanitize
        if main_value not in music_directories and os.path.exists(main_value):
            music_directories.append(main_value)
            main_window['music_dirs'].update(music_directories)
            refresh_tray()
            save_settings()
            index_all_tracks()
    elif main_event in {'settings_file', 'o:79'}:
        try: os.startfile(settings_file)
        except OSError: Popen(f'explorer /select,"{fix_path(settings_file)}"')
    elif main_event == 'music_dirs':
        with suppress(IndexError):
            Popen(f'explorer "{fix_path(main_values["music_dirs"][0])}"')
    # timer
    elif main_event == 'cancel_timer':
        main_window['timer_text'].update(value='No Timer Set')
        main_window['timer_error'].update(visible=False)
        main_window['cancel_timer'].update(visible=False)
    elif (main_event in {'\r', 'special 16777220', 'special 16777221', 'timer_submit'}
          and main_values['tab_group'] == 'tab_timer'):
        try:
            timer_value = main_values['minutes']
            if timer_value.isdigit():
                seconds = abs(float(main_values['minutes'])) * 60
            elif timer_value.count(':') == 1:
                if timer_value[-3:].strip().upper() in ('PM', 'AM'):
                    timer_value = timer_value[timer_value:-3]
                elif timer_value[-2:].upper() in ('PM', 'AM'):
                    timer_value = timer_value[timer_value:-2]
                to_stop = datetime.strptime(timer_value + time.strftime(',%Y,%m,%d,%p'), '%I:%M,%Y,%m,%d,%p')
                seconds_delta = (to_stop - datetime.now()).total_seconds()
                if seconds_delta < 0: seconds_delta += 43200
                seconds = seconds_delta
            else:
                raise ValueError()
            timer = time.time() + seconds
            timer_set_to = datetime.now() + timedelta(minutes=seconds // 60)
            if platform.system() == 'Windows': timer_set_to = timer_set_to.strftime('%#I:%M %p')
            else: timer_set_to = timer_set_to.strftime('%-I:%M %p')  # Linux
            main_window['timer_text'].update(value=f'Timer set for {timer_set_to}')
            main_window['cancel_timer'].update(visible=True)
            main_window['timer_error'].update(visible=False)
        except ValueError:
            for i in range(3):
                main_window['timer_error'].update(visible=True, text_color='#ffcccb')
                main_window.read(10)
                main_window['timer_error'].update(text_color='red')
                main_window.read(10)
    elif main_event in {'shut_off', 'hibernate', 'sleep', 'other_daemon_actions'}:
        change_settings('timer_hibernate_computer', main_values['hibernate'])
        change_settings('timer_sleep_computer', main_values['sleep'])
        change_settings('timer_shut_off_computer', main_values['shut_off'])

    if time.time() - progress_bar_last_update > 0.5:
        progress_bar: Sg.Slider = main_window['progress_bar']
        if playing_status == 'NOT PLAYING': progress_bar.update(0, disabled=True)
        elif music_queue:
            with suppress(ZeroDivisionError):
                get_track_position()
                progress_bar.update(track_position, range=(0, track_length), disabled=False)
            update_progress_bar_text = True
            progress_bar_last_update = time.time()
        elif not playing_live:
            print('"elif not playing_live" in update progress bar ran')
            playing_status = 'NOT PLAYING'
    if update_progress_bar_text:
        elapsed_time_text, time_left_text = create_progress_bar_text(track_position, track_length)
        main_window['time_elapsed'].update(value=elapsed_time_text)
        main_window['time_left'].update(value=time_left_text)
    if playing_status == 'PLAYING' and p_r_button.metadata != 'PLAYING':
        p_r_button.update(image_data=PAUSE_BUTTON_IMG)
    elif playing_status == 'PAUSED' and p_r_button.metadata != 'PAUSED':
        p_r_button.update(image_data=PLAY_BUTTON_IMG)
    elif playing_status == 'NOT PLAYING' and p_r_button.metadata != 'NOT PLAYING':
        if p_r_button.metadata == 'PLAYING': p_r_button.update(image_data=PLAY_BUTTON_IMG)
        main_window['time_elapsed'].update(value='0:00')
        main_window['time_left'].update(value='0:00')
    p_r_button.metadata = playing_status
    return True


def read_playlist_selector_window():
    global pl_selector_window, tray_playlists, pl_files, pl_name, pl_editor_window
    pl_selector_event, pl_selector_values = pl_selector_window.read(timeout=5)
    if pl_selector_event in {None, 'Escape:27', 'q'}:
        active_windows['playlist_selector'] = False
        pl_selector_window.close()
        return
    if pl_selector_event in {'del_pl', 'Delete:46'}:
        pl_name = pl_selector_values.get('playlist_combo', '')
        if pl_name in playlists:
            del playlists[pl_name]
            save_settings()
        playlist_names = tuple(settings['playlists'].keys())
        default_playlist_name = playlist_names[0] if playlist_names else ''
        pl_selector_window['playlist_combo'].update(value=default_playlist_name, values=playlist_names)
        pl_selector_window.refresh()
        if active_windows['main']:
            main_window['playlists'].update(value=default_playlist_name, values=playlist_names)
        tray_playlists.clear()
        tray_playlists.append('Create/Edit a Playlist')
        tray_playlists += [f'PL: {pl}' for pl in playlists.keys()]
    elif (pl_selector_event in {'edit_pl', 'create_pl', 'e', 'n', 'e:69', 'n:78'} and
          not active_windows['playlist_editor']):
        pl_name = pl_selector_values.get('playlist_combo', '') if pl_selector_event in {'edit_pl', 'e', 'e:69'} else ''
        window_location = get_window_location('playlist_editor')
        pl_files = playlists.get(pl_name, [])
        pl_selector_window.close()
        pl_editor_layout = create_playlist_editor(settings, pl_files, pl_name)
        pl_editor_window = Sg.Window('Playlist Editor', pl_editor_layout, finalize=True, icon=WINDOW_ICON,
                                     return_keyboard_events=True, location=window_location)
        pl_editor_window.TKroot.focus_force()
        pl_editor_window.normal()
        set_save_position_callback(pl_editor_window, 'playlist_editor')
        if pl_name == '': pl_editor_window['playlist_name'].set_focus()
        else:
            pl_editor_window['tracks'].set_focus()
            pl_editor_window['tracks'].update(set_to_index=0)
        active_windows['playlist_editor'], active_windows['playlist_selector'] = True, False
    elif pl_selector_event in {'Up:38', 'Down:40'}:
        with suppress(KeyError, IndexError, ValueError):
            pl_selector_combo = pl_selector_window['playlist_combo']
            pl_index = pl_selector_combo.Values.index(pl_selector_values['playlist_combo'])
            new_index = max(pl_index + {'Up:38': -1, 'Down:40': 1}[pl_selector_event], 0)
            pl_selector_combo.update(value=pl_selector_combo.Values[new_index])


def read_playlist_editor_window():
    global pl_files, pl_editor_last_event, pl_name, tray_playlists, pl_selector_window
    pl_editor_event, pl_editor_values = pl_editor_window.read(timeout=5)
    open_pl_selector = False
    if pl_editor_event == Sg.TIMEOUT_KEY: pass
    elif pl_editor_event in {None, 'Escape:27', 'Cancel'} and pl_editor_last_event not in {'Add tracks', 'f:70'}:
        active_windows['playlist_editor'] = False
        pl_editor_window.close()
        open_pl_selector = True
    elif pl_editor_event == 'playlist_name':
        # disable save button if playlist name is empty else enable
        pl_editor_window['save'].update(disabled=not pl_editor_values['playlist_name'])
    elif pl_editor_event in {'save', 's:83'}:
        new_name = pl_editor_values['playlist_name']
        pl_files = pl_files.copy()
        if pl_name != new_name:
            if pl_name in playlists: del playlists[pl_name]
            pl_name = new_name
        playlists[pl_name] = pl_files
        if active_windows['main'] and not settings['mini_mode']:
            playlist_names = tuple(playlists.keys())
            main_window['playlists'].update(value=playlist_names[0], values=playlist_names, visible=True)
            main_window['play_playlist'].update(visible=True)
        save_settings()
        active_windows['playlist_editor'] = False
        pl_editor_window.close()
        open_pl_selector = True
        tray_playlists.clear()
        tray_playlists.append('Create/Edit a Playlist')
        tray_playlists += [f'PL: {pl}' for pl in playlists.keys()]
    elif pl_editor_event in {'move_up', 'u:85'}:  # u:85 is Ctrl + U
        if pl_editor_values['tracks']:
            to_move = pl_editor_window['tracks'].get_list_values().index(pl_editor_values['tracks'][0])
            if to_move > 0:
                new_i = to_move - 1
                pl_files.insert(new_i, pl_files.pop(to_move))
                formatted_tracks = [f'{i + 1}. {os.path.basename(path)}' for i, path in enumerate(pl_files)]
                pl_editor_window['tracks'].update(values=formatted_tracks, set_to_index=new_i,
                                                  scroll_to_index=max(new_i - 3, 0))
    elif pl_editor_event in {'move_down', 'd:68'}:  # d:68 is Ctrl + D
        if pl_editor_values['tracks']:
            to_move = pl_editor_window['tracks'].get_list_values().index(pl_editor_values['tracks'][0])
            if to_move < len(pl_files) - 1:
                new_i = to_move + 1
                pl_files.insert(new_i, pl_files.pop(to_move))
                formatted_tracks = [f'{i + 1}. {os.path.basename(path)}' for i, path in enumerate(pl_files)]
                pl_editor_window['tracks'].update(values=formatted_tracks, set_to_index=new_i,
                                                  scroll_to_index=max(new_i - 3, 0))
    elif pl_editor_event in {'Add tracks', 'f:70'}:
        fd = wx.FileDialog(None, 'Select Music File(s)', defaultDir=DEFAULT_DIR, wildcard=MUSIC_FILE_TYPES,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        if fd.ShowModal() != wx.ID_CANCEL:
            file_paths = fd.GetPaths()
            pl_files += [file_path for file_path in file_paths if valid_music_file(file_path)]
            pl_editor_window.TKroot.focus_force()
            pl_editor_window.normal()
            formatted_tracks = [f'{i + 1}. {os.path.basename(path)}' for i, path in enumerate(pl_files)]
            new_i = len(formatted_tracks) - 1  # - len(new_files)
            pl_editor_window['tracks'].update(formatted_tracks, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif pl_editor_event in {'Remove track', 'r:82'}:  # r:82 is Ctrl + R
        if pl_editor_values['tracks']:
            index_to_rm = pl_editor_window['tracks'].get_list_values().index(pl_editor_values['tracks'][0])
            with suppress(ValueError): pl_files.pop(index_to_rm)
            formatted_tracks = [f'{i + 1}. {os.path.basename(path)}' for i, path in enumerate(pl_files)]
            new_i = max(index_to_rm - 1, 0)
            pl_editor_window['tracks'].update(formatted_tracks, set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    elif pl_editor_event in {'Up:38', 'Down:40', 'Prior:33', 'Next:34'} and pl_editor_values['tracks']:
        move = {'Up:38': -1, 'Down:40': 1, 'Prior:33': -3, 'Next:34': 3}[pl_editor_event]
        new_i = pl_editor_window['tracks'].get_list_values().index(pl_editor_values['tracks'][0]) + move
        new_i = min(max(new_i, 0), len(pl_files) - 1)
        pl_editor_window['tracks'].update(set_to_index=new_i, scroll_to_index=max(new_i - 3, 0))
    if open_pl_selector:
        active_windows['playlist_selector'] = True
        window_location = get_window_location('playlist_selector')
        pl_selector_window = Sg.Window('Playlist Selector', create_playlist_selector(settings), finalize=True,
                                       icon=WINDOW_ICON, return_keyboard_events=True, location=window_location)
        pl_selector_window.TKroot.focus_force()
        pl_selector_window.normal()
        set_save_position_callback(pl_selector_window, 'playlist_selector')
    pl_editor_last_event = pl_editor_event


def read_play_url_window():
    play_url_event, play_url_values = play_url_window.read(timeout=5)
    if play_url_event in {None, 'Escape:27', 'q'}:
        active_windows['play_url'] = False
        play_url_window.close()
    elif play_url_event in {'\r', 'special 16777220', 'special 16777221', 'Submit'}:
        active_windows['play_url'] = False
        play_url_window.close()
        url_to_play = play_url_values['url']
        if play_url_values['play_immediately'] or not music_queue and not next_queue:
            music_queue.insert(0, url_to_play)
            play(url_to_play)
        elif play_url_values['queue']:
            music_queue.append(url_to_play)
            if len(music_queue) == 1: play(url_to_play)
        else: next_queue.append(url_to_play)  # Add to Next Queue


def create_shortcut(_shortcut_path):
    """ creates shortcut if run_on_startup else removes existing shortcut """
    def _create_shortcut():
        with suppress(com_error):
            shortcut_exists = os.path.exists(_shortcut_path)
            if settings['run_on_startup'] and not shortcut_exists:
                # noinspection PyUnresolvedReferences
                pythoncom.CoInitialize()
                shell = win32com.client.Dispatch('WScript.Shell')
                shortcut = shell.CreateShortCut(_shortcut_path)
                if IS_FROZEN:
                    target = f'{starting_dir}\\Music Caster.exe'
                else:
                    bat_file = f'{starting_dir}\\music_caster.bat'
                    if os.path.exists(bat_file):
                        with open('music_caster.bat', 'w') as _f:
                            _f.write(f'pythonw {os.path.basename(sys.argv[0])}')
                    target = bat_file
                    shortcut.IconLocation = f'{starting_dir}\\icon.ico'
                shortcut.Targetpath = target
                shortcut.WorkingDirectory = starting_dir
                shortcut.WindowStyle = 1  # 7 - Minimized, 3 - Maximized, 1 - Normal
                shortcut.save()
            elif not settings['run_on_startup'] and shortcut_exists:
                os.remove(_shortcut_path)
    if not settings.get('DEBUG', False): Thread(target=_create_shortcut, name='CreateShortcut').start()


def get_latest_release(ver, force=False):
    """ Returns either False or {ver: cached link to the latest setup} """
    releases_url = 'https://api.github.com/repos/elibroftw/music-caster/releases/latest'
    release = requests.get(releases_url).json()
    latest_ver = release['tag_name'][1:]
    _version = [int(x) for x in ver.split('.')]
    compare_ver = [int(x) for x in latest_ver.split('.')]
    if compare_ver > _version or force:
        for asset in release['assets']:
            # check if setup exists
            if 'exe' in asset['name']:
                return {'version': latest_ver, 'setup': asset['browser_download_url']}
    return False


def auto_update(auto_start=True):
    global update_available
    try:
        release = get_latest_release(VERSION, force=(not IS_FROZEN or settings.get('DEBUG', False)))
        if release:
            latest_ver = release['version']
            setup_dl_link = release['setup']
            app_log.info(f'Update found: v{latest_ver}, auto_start={auto_start}')
            print('Installer Link:', setup_dl_link)
            if settings.get('DEBUG', False) or not setup_dl_link: return
            if IS_FROZEN and (os.path.exists(UNINSTALLER) or os.path.exists('Updater.exe')):
                if os.path.exists(UNINSTALLER):
                    # only show message on startup to not confuse the user
                    cmd = 'MC_Installer.exe /VERYSILENT /FORCECLOSEAPPLICATIONS /MERGETASKS="!desktopicon"'
                    if auto_start:
                        cmd_args = ' '.join(sys.argv[1:])
                        cmd += f' && "Music Caster.exe" {cmd_args}'  # auto start is True when updating on startup
                        temp_tray = SgWx.SystemTray(menu=[], data_base64=UNFILLED_ICON)
                        temp_tray.show_message('Music Caster', f'Downloading update v{latest_ver}', time=5000)
                        temp_tray.update(tooltip=f'Downloading update v{latest_ver}')
                    else: temp_tray = tray
                    download(setup_dl_link, 'MC_Installer.exe')
                    if auto_start:
                        temp_tray.hide()
                        temp_tray.close()
                    Popen(cmd, shell=True)
                else:
                    os.startfile('Updater.exe')
                    time.sleep(2)
                sys.exit()
            else:
                update_available = f'Update v{latest_ver} is available'
    except requests.ConnectionError: pass


def send_info():
    with suppress(requests.ConnectionError):
        requests.post('https://en3ay96poz86qa9.m.pipedream.net', json={'MAC': get_mac(), 'VERSION': VERSION})


def init_youtube_dl():  # 1 - 1.4 seconds
    global ydl
    ydl = YoutubeDL()


def activate_instance(port):
    r_text = ''
    while port <= 2003 and not r_text:
        with suppress(requests.exceptions.InvalidSchema, requests.ConnectionError):
            if args.exit:
                r_text = requests.post(f'http://127.0.0.1:{port}/exit/').text
            elif args.paths:  # MC was supplied a path to a folder/file
                r_text = requests.post(f'http://127.0.0.1:{port}/play/',
                                       data={'paths': args.paths, 'queue': args.queue}).text
            else:
                r_text = requests.post(f'http://127.0.0.1:{port}/').text
        port += 1


def quit_if_running():
    if is_already_running(threshold=1 if os.path.exists(UNINSTALLER) else 2) or DEBUG:
        print('Another instance of Music Caster was found' if not DEBUG else '')
        activate_instance(PORT)
        if IS_FROZEN and not DEBUG: sys.exit()
    return False


log_format = logging.Formatter('%(asctime)s %(levelname)s (%(lineno)d): %(message)s')
try:
    os.remove('music_caster.log')
except FileNotFoundError: pass
except PermissionError:
    # music_caster.log being open for write implies that an instance is already running
    if IS_FROZEN or DEBUG:
        activate_instance(PORT)
        sys.exit()
log_handler = RotatingFileHandler('music_caster.log', maxBytes=5242880, backupCount=1, encoding='UTF-8')
log_handler.setFormatter(log_format)
app_log = logging.getLogger('music_caster')
app_log.setLevel(logging.INFO)
app_log.addHandler(log_handler)
app_log.propagate = False  # disable console output
quit_if_running() or (args.exit and sys.exit())  # quit if running or if --exit was supplied to command line
load_settings()
init_ydl_thread = Thread(target=init_youtube_dl, daemon=True, name='InitYoutubeDL')
init_ydl_thread.start()
audio_player = AudioPlayer()
# check for update and update if no starting arguments were supplied or if the update flag was used
if len(sys.argv) == 1 and settings['auto_update'] or args.update: auto_update()
if not settings.get('DEBUG', False): Thread(target=send_info, daemon=True, name='SendInfo').start()
# Access startup folder by entering "Startup" in Explorer address bar
SHORTCUT_PATH = f'{winshell.startup()}\\Music Caster.lnk'
try:
    create_shortcut(SHORTCUT_PATH)
    if os.path.exists(UNINSTALLER): add_reg_handlers(f'{starting_dir}/Music Caster.exe',
                                                     add_folder_context=settings['folder_context_menu'])
    with suppress(FileNotFoundError, OSError): os.remove('MC_Installer.exe')
    rmtree('Update', ignore_errors=True)
    start = time.time()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.05)
        while True:
            if not s.connect_ex(('localhost', PORT)) == 0:  # if port is not occupied
                try:  # start server with the unoccupied PORT
                    server_kwargs = {'host': '0.0.0.0', 'port': PORT, 'threaded': True}
                    Thread(target=app.run, name='FlaskServer', daemon=True, kwargs=server_kwargs).start()
                    break
                except OSError: PORT += 1
            else: PORT += 1
    print(f'Running on port {PORT} (Time Taken: {round(time.time() - start, 1)}s)')
    repeat_menu = ['Repeat All ✓' if settings['repeat'] is False else 'Repeat All',
                   'Repeat One ✓' if settings['repeat'] else 'Repeat One',
                   'Repeat Off ✓' if settings['repeat'] is None else 'Repeat Off']

    menu_def_1 = ['', ['Settings', 'Refresh Library', 'Refresh Devices', 'Select Device', device_names,
                       'Timer', ['Set Timer', 'Cancel Timer'], 'Play',
                       ['Live System Audio', 'URL', ['Play URL', 'Queue URL', 'Play URL Next'], 'Folders', tray_folders,
                        'Playlists', tray_playlists, 'Play File(s)', 'Play All'], 'Exit']]
    menu_def_2 = ['', ['Settings', 'Refresh Library', 'Refresh Devices', 'Select Device', device_names,
                       'Timer', ['Set Timer', 'Cancel Timer'], 'Controls',
                       ['Locate File', 'Repeat Options', repeat_menu, 'Stop', 'Previous Track', 'Next Track',
                        'Pause'], 'Play',
                       ['Live System Audio', 'URL', ['Play URL', 'Queue URL', 'Play URL Next'], 'Folders', tray_folders,
                        'Playlists', tray_playlists, 'Play File(s)', 'Play File Next', 'Play All'], 'Exit']]
    menu_def_3 = ['', ['Settings', 'Refresh Library', 'Refresh Devices', 'Select Device', device_names,
                       'Timer', ['Set Timer', 'Cancel Timer'], 'Controls',
                       ['Locate File', 'Repeat Options', repeat_menu, 'Stop', 'Previous Track', 'Next Track',
                        'Resume'], 'Play',
                       ['Live System Audio', 'URL', ['Play URL', 'Queue URL', 'Play URL Next'], 'Folders', tray_folders,
                        'Playlists', tray_playlists, 'Play File(s)', 'Play File Next', 'Play All'], 'Exit']]
    print('Connecting to Discord')
    rich_presence = pypresence.Presence(MUSIC_CASTER_DISCORD_ID)
    if settings['discord_rpc']:
        with suppress(py_presence_errors): rich_presence.connect()
    print('Connected to Discord')
    pynput.keyboard.Listener(on_press=on_press, on_release=on_release).start()  # daemon=True by default
    init_ydl_thread.join()
    tooltip = 'Music Caster [DEBUG]' if settings.get('DEBUG', False) else 'Music Caster'
    # active_windows = {'main': activate_main_window, 'playlist_selector': activate_playlist_selector,
    #                   'playlist_editor': activate_playlist_editor, 'play_url': activate_play_url}
    tray = SgWx.SystemTray(menu=menu_def_1, data_base64=UNFILLED_ICON, tooltip=tooltip)
    if not music_directories:
        music_directories = change_settings('music_directories', [home_music_dir])
        index_all_tracks()
    if settings['notifications']:
        if show_pygame_error:
            tray.show_message('Music Caster', 'ERROR: No local audio device found', time=5000)
        if settings['update_message'] == '':
            welcome_msg = 'Thanks for installing Music Caster.\nMusic Caster is running in the tray.'
            tray.show_message('Music Caster', welcome_msg, time=5000)
        elif settings['update_message'] != UPDATE_MESSAGE:
            tray.show_message('Music Caster Updated', UPDATE_MESSAGE, time=5000)
    if update_available and IS_FROZEN:
        tray.show_message('Music Caster', update_available, time=5000)
    change_settings('update_message', UPDATE_MESSAGE)
    temp = (settings['timer_shut_off_computer'], settings['timer_hibernate_computer'], settings['timer_sleep_computer'])
    if temp.count(True) > 1:  # Only one of the below can be True
        if settings['timer_shut_off_computer']: change_settings('timer_hibernate_computer', False)
        change_settings('timer_sleep_computer', False)
    if settings['save_queue_sessions'] and settings['populate_queue_startup']:  # mutually exclusive
        change_settings('populate_queue_startup', False)
    cast_last_checked = time.time()
    Thread(target=background_tasks, daemon=True, name='BackgroundTasks').start()
    Thread(target=start_chromecast_discovery, daemon=True, name='CCDiscovery').start()
    if args.paths:
        # wait until previous device has been found or if it hasn't been found
        while all((settings['previous_device'], cast is None, stop_discovery)): time.sleep(0.3)
        play_paths(args.paths, queue_only=args.queue)
    elif settings['save_queue_sessions']:
        queues = settings['queues']
        done_queue.extend(queues.get('done', []))
        music_queue.extend(queues.get('music', []))
        next_queue.extend(queues.get('next', []))
    elif settings['populate_queue_startup']:
        indexing_tracks_thread.join()
        play_all(queue_only=True)
    print('Running in tray')
    pause_resume = {'PAUSED': resume, 'PLAYING': pause}
    tray_actions = {
        '__ACTIVATED__': activate_main_window,
        'Refresh Library': index_all_tracks,
        'Refresh Devices': lambda: Thread(target=start_chromecast_discovery, daemon=True, name='CCDiscovery').start(),
        # isdigit should be an if statement
        'Settings': lambda: activate_main_window('tab_settings'),
        'Create/Edit a Playlist': create_edit_playlists,
        # PL should be an if statement
        'Set Timer': lambda: activate_main_window('tab_timer'),
        'Cancel Timer': cancel_timer,
        'Live System Audio': stream_live_audio,
        'Play URL': activate_play_url,
        'Queue URL': lambda: activate_play_url('Queue'),
        'Play URL Next': lambda: activate_play_url('Play Next'),
        'Play File(s)': lambda: Thread(target=file_action, daemon=True, name='PlayFile').start(),
        'Play All': play_all,
        'Play File Next': lambda: Thread(target=play_next, name='PlayNext', daemon=True).start(),
        'Pause': pause,
        'Resume': resume,
        'Next Track': next_track,
        'Previous Track': prev_track,
        'Stop': lambda: stop('tray'),
        'web_play_files': lambda: 'pass',
        'Repeat One': lambda: change_settings('repeat', True),
        'Repeat All': lambda: change_settings('repeat', False),
        'Repeat Off': lambda: change_settings('repeat', None),
        'Locate File': locate_file,
        'Exit': exit_program,
        '': lambda: None,
    }
    while True:
        tray_item = tray.Read(timeout=30 if any(active_windows.values()) else 100)
        tray_actions.get(tray_item, lambda: other_tray_actions(tray_item))()
        tray_actions.get(daemon_command, lambda: other_tray_actions(daemon_command))()
        daemon_command = ''
        if active_windows['main']: read_main_window()
        if active_windows['playlist_selector']: read_playlist_selector_window()
        if active_windows['playlist_editor']: read_playlist_editor_window()
        if active_windows['play_url']: read_play_url_window()
except Exception as e:
    handle_exception(e, True)
