
import os
import socket
import sublime
import sublime_plugin
import subprocess
import sys
import threading


DEFAULT_PORT = 22000
SIZE = 1024


def settings():
    return sublime.load_settings("Collaboration.sublime-settings")

def collab_name(c):
    if c.has_key('name'):
        return c['name']
    elif c.has_key('host'):
        return c['host']

def get_host():
    return socket.gethostbyname(socket.gethostname())


class CollabStartCommand(sublime_plugin.WindowCommand):
    """
    The Command for starting a new collaboration.
    Collaborations can be started on the active view
    or a new view. The hosts can be defined in the
    packages settings, or a custom host can be defined.
    """
    def collaborators(self):
        """ Return a list of valid collaborators from the package settings """
        s = settings()
        collabs = s.get('collaborators')
        if collabs is not None:
            valid = [c for c in collabs if c.has_key('host')]
            return valid
        return []

    def port(self):
        """ Return the port defined in the package settings """
        s = settings()
        port = s.get('port')
        if port is None:
            port = DEFAULT_PORT
        return port

    def run(self, new=False, custom=False):
        self.new = new
        if custom:
            self.window.show_input_panel("Collaborate with:", "", self.start_custom, None, None)
        else:
            collabs = self.collaborators()
            items = [[collab_name(c), c['host']] for c in collabs]
            self.window.show_quick_panel(items, self.start_with)

    def start_with(self, index):
        if index < 0:
            return
        collabs = self.collaborators()
        if len(collabs) > index:
            c = collabs[index]
            self.start(c['host'], self.port(), c['name'])

    def start_custom(self, hoststr):
        """
        Start a collaboration with a custom host and port.
        If no port is provided, the default port is used.
        Assumes format of host:port
        """
        split = hoststr.split(':')
        host = split[0].strip()
        if len(split) > 1:
            port = split[1].strip()
        else:
            port = self.port()
        self.start(host, port)

    def start(self, host, port, name=None):
        # determine file
        w = sublime.active_window()
        v = w.active_view()
        if self.new:
            v = w.new_file()
        c = Collaboration(host, port, v, name)
        c.start()
        # show message
        # ensure server is started
        # TODO: ---
        # call out for response


class CollabEventListener(sublime_plugin.EventListener):
    def on_selection_modified(self, view):
        #view.run_command('collab_client_send')
        pass



class Collaborator(object):
    """
    A collaborator represented by host, port, and name.
    The only required option is host.
    """
    def __init__(self, host, port=None, name=None):
        self.host = host
        self.port = port
        self.name = name

    @property
    def name(self):
        if self._name is not None:
            return self._name
        return host
    @name.setter
    def name(self, value):
        self._name = value


class Collaboration(Collaborator):
    """
    Represents a collaboration. Stores information
    such as the host and port, as well as the source
    view id and the connection socket.
    """
    instances = {}

    @staticmethod
    def register(collab):
        Collaboration.instances[collab.view.id()] = collab

    def __init__(self, host, port, view, name=None):
        self.view = view
        self.host = host
        self.port = port
        self.name = name
        self.socket = None
        self.isDead = True

    def __del__(self):
        self.close()

    def isConnected(self):
        return self.socket is not None

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
        except socket.error, (value, self.message):
            self.close()
            self.isDead = True

    def close(self):
        """
        Close the socket if it is still open.
        """
        if self.socket:
            self.socket.close()
        self.socket = None

    def start(self):
        """
        Start the collaboration. This will reach out to the
        host and request that the collaboration be confirmed.
        If the collaboration is refused it will be removed.
        """
        self.connect()
        self.request_start()

    def request_start(self):
        data = dict(
            type='start',
            host=get_host(),
        )

        f = self.view.file_name()
        if f is None:
            f = 'new file'
        msg = 'Starting collaboration on {0} with {1}'.format(f, self.name)
        print(msg + ' - {0}:{1}'.format(self.host, self.port))
        sublime.status_message(msg)

        msg = ClientMessage(self.socket, data, 5)
        msg.start()
        self.handle_messages([msg])

    def send_command(self, cmd):
        data = dict(
            type='cmd'
        )
        msg = ClientMessage(self.socket, data)
        msg.start()
        self.handle_messages([msg])

    def handle_messages(self, msgs):
        remaining = []
        for m in msgs:
            if m.is_alive():
                remaining.append(m)
                if m.data['type'] == 'start':
                    self.view.set_status('collab', 'waiting for collab response: {0}'.format(self.host))
                continue
            if m.result == False:
                sublime.status_message('Collaboration Error: {0}'.format(m.message))
                continue
            self.handle_response(m)
        msgs = remaining
        # check if we have msgs left to handle
        if len(msgs):
            sublime.set_timeout(lambda: self.handle_messages(msgs), 20)
            return

    def handle_response(self, msg):
        response = eval(msg.response)
        typ = msg.data['type']
        print('got response: {0}'.format(response))

        if typ == 'start':
            self.view.erase_status('collab')
            if int(response['accept']):
                # start request accepted
                Collaboration.register(self)



class ClientMessage(threading.Thread):
    def __init__(self, socket, data, timeout):
        self.socket = socket
        self.data = data
        self.timeout = timeout
        self.size = SIZE
        self.message = None
        self.result = None
        self.response = None
        threading.Thread.__init__(self)

    def run(self):
        try:
            datastr = str(self.data)
            self.socket.send(datastr)
            self.response = self.socket.recv(self.size)
            self.result = True
        except Exception as e:
            print(e)
            self.result = False



