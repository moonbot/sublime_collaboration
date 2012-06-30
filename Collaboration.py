
import os
import socket
import sublime
import sublime_plugin
import subprocess
import sys
import threading

HOST = 'localhost'
PORT = 50000
SIZE = 1024

SRC_VIEW = 97
DST_VIEW = 100


def get_view(id):
    for w in sublime.windows():
        for v in w.views():
            if v.id() == id:
                return v

def src_view():
    return get_view(SRC_VIEW)
def set_src_view(v):
    global SRC_VIEW
    SRC_VIEW = v.id()

def dst_view():
    return get_view(DST_VIEW)
def set_dst_view(v):
    global DST_VIEW
    DST_VIEW = v.id()

def settings():
    return sublime.load_settings("Collaboration.sublime-settings")

def valid_collaborators():
    s = settings()
    collabs = s.get('collaborators')
    if collabs is not None:
        valid = [c for c in collabs if c.has_key('host')]
        return valid
    return []

def collab_name(c):
    if c.has_key('name'):
        return c['name']
    elif c.has_key('host'):
        return c['host']

class CollabStartCommand(sublime_plugin.ApplicationCommand):
    def run(self):
        print('hi')


class CollabStartCommand(sublime_plugin.WindowCommand):
    def run(self, new=False, custom=False):
        self.new = new
        if custom:
            self.window.show_input_panel("Collaborate with:", "", self.start, None, None)
        else:
            collabs = valid_collaborators()
            items = [[collab_name(c), c['host']] for c in collabs]
            self.window.show_quick_panel(items, self.start_with_collab)

    def start_with_collab(self, index):
        if index < 0:
            return
        collabs = valid_collaborators()
        if len(collabs) > index:
            c = collabs[index]
            self.start(c['host'], c['name'])

    def start(self, host, name=None):
        w = sublime.active_window()
        v = w.active_view()
        if self.new:
            v = w.new_file()
        set_src_view(v)

        if name is None:
            name = host
        f = 'new file' if self.new else v.file_name()
        msg = 'Starting collaboration on {0} with {1}'.format(f, name)
        print(msg)
        sublime.status_message(msg)


class CollabClientSendCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        sels = self.view.sel()
        if len(sels) == 0:
            return
        sel = sels[0]
        # get most recent command
        cmd = self.view.command_history(0, True)
        # send command
        threads = []
        thread = ClientCommand(sel, cmd, 5)
        threads.append(thread)
        thread.start()
        # handle threads
        self.handle_threads(threads)

    def handle_threads(self, threads):
        remaining = []
        for t in threads:
            if t.is_alive():
                remaining.append(t)
                continue
            if t.result == False:
                sublime.status_message('Collaboration: {0}'.format(t.message))
                continue
            self.handle_data(t.data)
        threads = remaining
        # check if we have threads left to handle
        if len(threads):
            sublime.set_timeout(lambda: self.handle_threads(threads), 20)
            return

    def handle_data(self, data):
        d = eval(data)
        cmd, sel = None, None
        if d.has_key('cmd'):
            cmd = d['cmd']
        if d.has_key('sel'):
            sel = d['sel']
        print(cmd)

        # temp
        w = sublime.active_window()
        v = w.active_view()
        if v.id() == SRC_VIEW:
            sublime.status_message('Collaboration: Cannot send and receive in the same view')
            return

        v = get_view(SRC_VIEW)
        if v is not None:
            sublime.status_message('Collaboration: Updating view {0}'.format(v.id()))
            if cmd[0].strip() != '':
                v.run_command(cmd[0], cmd[1])
            #v.sel().add(sublime.Region(*sel))


class CollabEvents(sublime_plugin.EventListener):
    def on_selection_modified(self, view):
        if view.id() != SRC_VIEW:
            #view.run_command('collab_client_send')
            pass


class ClientCommand(threading.Thread):
    def __init__(self, sel, cmd, timeout):
        self.sel = sel
        self.cmd = cmd
        self.host = HOST
        self.port = PORT
        self.size = SIZE
        self.timeout = timeout
        self.data = None
        self.result = None
        self.message = ''
        threading.Thread.__init__(self)

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
        except socket.error, (value, self.message):
            if s:
                s.close()
            self.result = False
        else:
            senddata = {'sel':self.sel, 'cmd':self.cmd}
            s.send(str(senddata))
            self.data = s.recv(self.size)
            self.result = True
            s.close()


