#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import subprocess
import requests
import urwid
import random


try:
    input = raw_input
except NameError:
    pass


class Song(object):
    def __init__(self, song_json):
        try:
            self._parse(song_json)
        except KeyError:
            pass

    def _parse(self, song_json):
        self.sid = song_json['sid']
        self.picture = song_json['picture']
        self.artist = song_json['artist']
        self.title = song_json['title']
        if self.title.isupper():
            self.title = self.title.title()

        self.length_in_sec = song_json['length']
        self.url = song_json['url']

    @staticmethod
    def parse(song_json):
        return Song(song_json)


class Player(object):
    def __init__(self):
        self.is_playing = False
        self.current_song = None
        self.player_process = None
        self.external_player = None
        self._detect_external_players()

    def _detect_external_players(self):
        supported_external_players = [
            ["mpv", "--really-quiet"],
            ["mplayer", "-really-quiet"],
            ["mpg123", "-q"],
        ]

        for external_player in supported_external_players:
            proc = subprocess.Popen(
                ["which", external_player[0]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            player_bin_path = proc.communicate()[0].strip()

            if player_bin_path and os.path.exists(player_bin_path):
                self.external_player = external_player
                break

        else:
            print("No supported player(mpv/mplayer/mpg123) found. Exit.")
            raise SystemExit()

    def play(self, song):
        if self.is_playing:
            self.stop()

        self.current_song = song
        self.player_process = subprocess.Popen(
            self.external_player + [self.current_song.url],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.is_playing = True

    def stop(self):
        self.is_playing = False

        if self.player_process is None:
            return
        try:
            self.player_process.terminate()
        except:
            pass


class DoubanFMApi:
    API_HOST_URL = "https://api.douban.com"
    TOKEN_HOST_URL = "https://www.douban.com"
    APP_NAME = "radio_android"
    VERSION = "642"
    KEY = "02f7751a55066bcb08e65f4eff134361"
    SECRET = "63cf04ebd7b0ff3b"

    def __init__(self):
        self.auth = None

    def login(self, email, password):
        rsp = requests.post('%s/service/auth2/token' % DoubanFMApi.TOKEN_HOST_URL, data={
            'username': email,
            'password': password,
            'client_id': DoubanFMApi.KEY,
            'client_secret': DoubanFMApi.SECRET,
            'grant_type': 'password',
            'apikey': DoubanFMApi.KEY,
        }).json()

        self.auth = "Bearer %s" % rsp['access_token']

    def get_redheart_songs(self):
        if self.auth is None:
            return

        auth_header = {'Authorization': self.auth}

        rsp = requests.get('%s/v2/fm/redheart/basic' % DoubanFMApi.API_HOST_URL, params={
            'app_name': DoubanFMApi.APP_NAME,
            'version': DoubanFMApi.VERSION,
        }, headers=auth_header).json()

        sids = ""
        for sid in rsp['songs']:
            if sid['playable'] is True:
                sids += sid['sid'] + '|'

        sids = sids[:-1]

        rsp = requests.post('%s/v2/fm/songs' % DoubanFMApi.API_HOST_URL, data={
            'sids': sids,
            'kbps': '128',
            'app_name': DoubanFMApi.APP_NAME,
            'version': DoubanFMApi.VERSION,
            'apikey': DoubanFMApi.KEY,
        }, headers=auth_header).json()

        return list(map(Song.parse, rsp))


class SongButton(urwid.Button):
    LAST_PRESSED_BTN = None

    def __init__(self, song, on_pressed_callback):
        self.on_pressed_callback = on_pressed_callback
        super(SongButton, self).__init__('', self._on_pressed, song)

        self._text = urwid.SelectableIcon(
            u'\N{BULLET} ' + song.title + ' - ' + song.artist,
            cursor_position=0)
        self._w = urwid.AttrMap(self._text, None, focus_map='reversed')

    @property
    def text(self):
        return self._text.text

    def set_text(self, text):
        self._text.set_text(text)

    def set_attr_map(self, attr_map):
        self._w.set_attr_map(attr_map)

    def mouse_event(self, size, event, button, x, y, focus):
        # 屏蔽鼠标点击
        pass

    def _on_pressed(self, button, song):
        # 按下按钮后, 改变按钮外观
        if SongButton.LAST_PRESSED_BTN is not None:
            SongButton.LAST_PRESSED_BTN.set_text(u'\N{BULLET}' + SongButton.LAST_PRESSED_BTN.text[1:])
            SongButton.LAST_PRESSED_BTN.set_attr_map({'playing': None})

        self.set_text(u'♫' + self.text[1:])
        self.set_attr_map({None: 'playing'})

        self.on_pressed_callback(button, song)
        SongButton.LAST_PRESSED_BTN = self


class SongListBox(urwid.ListBox):
    def __init__(self, songs, on_item_pressed_callback):
        super(SongListBox, self).__init__(urwid.SimpleFocusListWalker(
            [SongButton(song, on_item_pressed_callback) for song in songs]
        ))

        self._command_map['j'] = 'cursor down'
        self._command_map['k'] = 'cursor up'

    def keypress(self, size, key):
        if key in ('up', 'down', 'page up', 'page down', 'enter', ' ', 'j', 'k'):
            return super(SongListBox, self).keypress(size, key)

        if key in ('q', 'Q', 'esc'):
            # 发送退出信号
            urwid.emit_signal(self, 'exit')

        if key in ('p', 'P'):
            # 暂停/继续播放
            urwid.emit_signal(self, 'pause_or_play')

        if key in ('left', 'right'):
            # 下一首歌曲
            urwid.emit_signal(self, 'next_song')

        if key in ('m', 'M'):
            # 切换模式
            urwid.emit_signal(self, 'change_mode')


class UI:
    def __init__(self):
        self.player = Player()
        self.songs = []
        self.playing_song = None
        self.next_song_alarm = None
        self.main = None

        # 调色板
        self.palette = [
            ('reversed', '', '', '', 'standout', ''),
            ('playing', '', '', '', 'bold, g7', '#d06'),
            ('title', '', '', '', 'bold, g7', '#d06'),
        ]

        self._setup_ui()

    def _setup_ui(self):
        email = input('豆瓣账户 (Email地址): ')
        password = input('豆瓣密码: ')

        api = DoubanFMApi()
        api.login(email, password)
        self.songs = api.get_redheart_songs()

        # 头部
        title = urwid.Text(('title', ' ❤ 豆瓣 FM 红心歌曲 '))
        divider = urwid.Divider()
        header = urwid.Padding(urwid.Pile([divider, title, divider]), left=4, right=4)

        # 歌曲列表
        self.song_listbox = SongListBox(self.songs, self._on_item_pressed)

        # 页面
        self.main = urwid.Padding(
            urwid.Frame(self.song_listbox, header=header, footer=divider),
            left=4, right=4)

        # 注册信号回调
        urwid.register_signal(
            SongListBox, ['exit', 'pause_or_play', 'next_song', 'change_mode'])
        urwid.connect_signal(self.song_listbox, 'exit', self._on_exit)
        urwid.connect_signal(self.song_listbox, 'pause_or_play', self._on_exit)
        urwid.connect_signal(self.song_listbox, 'next_song', self.next_song())
        urwid.connect_signal(self.song_listbox, 'change_mode', self.change_mode())

        self.loop = urwid.MainLoop(self.main, palette=self.palette)
        self.loop.screen.set_terminal_properties(colors=256)

    def run(self):
        self.loop.run()

    def pause_or_play(self):
        # todo
        pass

    def next_song(self):
        # todo
        pass

    def change_mode(self):
        # todo
        pass

    def play(self, song):
        self.player.play(song)
        self.playing_song = song

        # 循环播放
        def next_song_alarm_handler(loop, user_data):
            self.play(self.playing_song)

        if self.next_song_alarm is not None:
            self.loop.remove_alarm(self.next_song_alarm)

        self.next_song_alarm = self.loop.set_alarm_in(
            self.playing_song.length_in_sec,
            next_song_alarm_handler, None)

    def _on_item_pressed(self, button, song):
        self.play(song)

    def _on_exit(self):
        self.player.stop()
        raise urwid.ExitMainLoop()


if __name__ == '__main__':
    UI().run()

