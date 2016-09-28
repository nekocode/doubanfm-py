#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import subprocess
import requests
import urwid
import uuid
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
    UUID = '408428bc' + str(uuid.uuid4()).replace('-', '')
    REDIRECT_URI = 'http://douban.fm'

    def __init__(self):
        self.auth = None

    def login(self, email, password):
        rsp = requests.post('%s/service/auth2/token' % DoubanFMApi.TOKEN_HOST_URL, data={
            'username': email,
            'password': password,
            'udid': DoubanFMApi.UUID,
            'client_id': DoubanFMApi.KEY,
            'client_secret': DoubanFMApi.SECRET,
            'redirect_uri': DoubanFMApi.REDIRECT_URI,
            'grant_type': 'password',
            'apikey': DoubanFMApi.KEY,
        }).json()

        self.auth = "Bearer %s" % rsp['access_token']

    def get_redheart_songs(self):
        if self.auth is None:
            return []

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
    def __init__(self, song, on_pressed_callback, index=0):
        super(SongButton, self).__init__('', on_pressed_callback)
        self.index = index
        self.song = song
        self.is_playing = False

        self._text = urwid.SelectableIcon(
            u'• %s - %s' % (song.title, song.artist),
            cursor_position=0)
        self._w = urwid.AttrMap(self._text, None, focus_map='reversed')
        self.set_is_playing(self.is_playing)

    # 设置按钮播放状态
    def set_is_playing(self, is_playing):
        self.is_playing = is_playing

        if is_playing:
            self._text.set_text(u'♫' + self._text.text[1:])
            self._w.set_attr_map({None: 'playing'})
        else:
            self._text.set_text(u'•' + self._text.text[1:])
            self._w.set_attr_map({'playing': None})

    def mouse_event(self, size, event, button, x, y, focus):
        # 屏蔽鼠标点击
        pass


class SongListBox(urwid.ListBox):
    def __init__(self, btns):
        super(SongListBox, self).__init__(urwid.SimpleFocusListWalker(btns))

        self._command_map['j'] = 'cursor down'
        self._command_map['k'] = 'cursor up'

    def keypress(self, size, key):
        if key in ('up', 'down', 'page up', 'page down', 'enter', ' ', 'j', 'k'):
            return super(SongListBox, self).keypress(size, key)

        if key in ('q', 'Q', 'esc'):
            # 发送退出信号
            urwid.emit_signal(self, 'exit')

        if key in ('s', 'S'):
            # 停止播放
            urwid.emit_signal(self, 'stop')

        if key in ('left', 'right'):
            # 下一首歌曲
            urwid.emit_signal(self, 'next_song')

        if key in ('m', 'M'):
            # 切换模式
            urwid.emit_signal(self, 'change_mode')


class UI:
    LOOP_MODE = {
        0: u'单曲循环',
        1: u'全部循环',
        2: u'随机播放',
    }

    def __init__(self):
        self.player = Player()
        self.btns = []
        self.playing_btn = None
        self.loop_mode = 0
        self.next_song_alarm = None
        self.main = None

        # 调色板
        self.palette = [
            ('reversed', '', '', '', 'standout', ''),
            ('playing', '', '', '', 'bold, g7', '#d06'),
            ('title', '', '', '', 'bold, g7', '#d06'),
            ('loop_mode', '', '', '', 'bold, g7', '#d06'),
            ('red', '', '', '', 'bold, #d06', ''),
        ]

        self._setup_ui()

    def _setup_ui(self):
        email = input('豆瓣账户 (Email地址): ')
        password = input('豆瓣密码: ')

        api = DoubanFMApi()
        api.login(email, password)
        songs = api.get_redheart_songs()

        # 头部
        self.title = urwid.Text('')
        self._update_title()
        divider = urwid.Divider()
        header = urwid.Padding(urwid.Pile([divider, self.title, divider]), left=4, right=4)

        # 歌曲列表
        index = 0
        for song in songs:
            self.btns.append(SongButton(song, self._on_item_pressed, index))
            index += 1
        self.song_listbox = SongListBox(self.btns)

        # 页面
        self.main = urwid.Padding(
            urwid.Frame(self.song_listbox, header=header, footer=divider),
            left=4, right=4)

        # 注册信号回调
        urwid.register_signal(
            SongListBox, ['exit', 'stop', 'next_song', 'change_mode'])
        urwid.connect_signal(self.song_listbox, 'exit', self._on_exit)
        urwid.connect_signal(self.song_listbox, 'stop', self.stop_song)
        urwid.connect_signal(self.song_listbox, 'next_song', self.next_song)
        urwid.connect_signal(self.song_listbox, 'change_mode', self.change_mode)

        self.loop = urwid.MainLoop(self.main, palette=self.palette)
        self.loop.screen.set_terminal_properties(colors=256)

    def _update_title(self):
        text = [
            ('title', u' ❤ 豆瓣 FM 红心歌曲 '),
            ('red', u'   LOOP: '),
            ('loop_mode', u'%s' % UI.LOOP_MODE[self.loop_mode]),
        ]

        if self.playing_btn is not None:
            playing_song = self.playing_btn.song
            text.extend([
                ('red', u'\n♫ %s - %s' % (playing_song.title, playing_song.artist)),
            ])

        self.title.set_text(text)

    def stop_song(self):
        if self.playing_btn is not None:
            self.playing_btn.set_is_playing(False)
        self.playing_btn = None

        self.player.stop()
        self._update_title()

        if self.next_song_alarm is not None:
            self.loop.remove_alarm(self.next_song_alarm)

    def next_song(self):
        # 单曲循环
        if self.loop_mode == 0:
            self._on_item_pressed(self.playing_btn)
        # 全部循环
        elif self.loop_mode == 1:
            index = self.playing_btn.index + 1
            if index >= len(self.btns):
                index = 0
            next_song_btn = self.btns[index]
            self._on_item_pressed(next_song_btn)
        # 随机播放
        elif self.loop_mode == 2:
            next_song_btn = self.btns[random.randint(0, len(self.btns) - 1)]
            self._on_item_pressed(next_song_btn)

    def change_mode(self):
        if self.loop_mode < 2:
            self.loop_mode += 1
        else:
            self.loop_mode = 0

        self._update_title()

    def _on_item_pressed(self, button):
        if self.playing_btn is not None:
            self.playing_btn.set_is_playing(False)
        self.playing_btn = button
        self.playing_btn.set_is_playing(True)

        playing_song = self.playing_btn.song
        self.player.play(playing_song)
        self._update_title()

        # 循环播放定时设置
        if self.next_song_alarm is not None:
            self.loop.remove_alarm(self.next_song_alarm)

        self.next_song_alarm = self.loop.set_alarm_in(
            playing_song.length_in_sec,
            lambda loop, data: self.next_song(), None)

    def _on_exit(self):
        self.player.stop()
        raise urwid.ExitMainLoop()

    def run(self):
        self.loop.run()


if __name__ == '__main__':
    UI().run()

