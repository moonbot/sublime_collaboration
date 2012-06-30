
import functools
import os
import select
import socket
import sublime
import sublime_plugin
import subprocess
import sys
import threading


DEFAULT_PORT = 22000
DEFAULT_SIZE = 4096


def settings():
    return sublime.load_settings("Collaboration.sublime-settings")

def collaborators():
    """
    Return a list of collaborators from the package settings.
    Validates the collaborators by leaving out those missing a host value.
    """
    s = settings()
    collabs = s.get('collaborators')
    if collabs is not None:
        valid = [Collaborator.fromSettings(c) for c in collabs if c.has_key('host')]
        return valid
    return []

def port():
    """ Return the port defined in the package settings """
    s = settings()
    port = s.get('port')
    if port is None:
        port = DEFAULT_PORT
    return port

def collab_name(c):
    if c.has_key('name'):
        return c['name']
    elif c.has_key('host'):
        return c['host']

def this_host():
    return socket.gethostbyname('localhost')

def this_name():
    return settings().get('name')

def main_thread(callback, *args, **kwargs):
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)



class CollabStartCommand(sublime_plugin.WindowCommand):
    """
    The Command for starting a new collaboration.
    Collaborations can be started on the active view
    or a new view. The hosts can be defined in the
    packages settings, or a custom host can be given.
    """

    def run(self, new=False, custom=False):
        self.new = new
        if custom:
            self.window.show_input_panel("Collaborate with:", "", self.start_custom, None, None)
        else:
            collabs = collaborators()
            items = [[c.name, c.host] for c in collabs]
            self.window.show_quick_panel(items, self.start_with_collaborator)

    def start_with_collaborator(self, index):
        if index < 0:
            return
        collabs = collaborators()
        if len(collabs) > index:
            c = collabs[index]
            self.start(c.host, c.port, c.name)

    def start_custom(self, hoststr):
        """
        Start a collaboration with a custom host and port.
        If no port is provided, the default port is used.
        Assumes format of host:port
        """
        split = hoststr.split(':')
        host = split[0].strip()
        if len(split) > 1:
            port = int(split[1].strip())
        else:
            port = self.port()
        self.start(host, port)

    def start(self, host, port, name=None):
        # determine file
        w = sublime.active_window()
        v = w.active_view()
        if self.new:
            v = w.new_file()
        c = Collaboration(v, host, port, name)
        c.start()
        # show message
        # ensure server is started
        # TODO: ---
        # call out for response


class CollabServerCommand(sublime_plugin.ApplicationCommand):
    def run(self, start=True):
        if start:
            Server.start()
        else:
            Server.stop()


class CollabEventListener(sublime_plugin.EventListener):
    def on_close(self, view):
        Collaboration.kill(view.id())

    def on_selection_modified(self, view):
        c = Collaboration.get(view.id())
        if c:
            c.send_command(view.command_history(0, True), view.sel())



class Collaborator(object):
    """
    A collaborator represented by host, port, and name.
    The only required data is host.
    """
    @staticmethod
    def fromSettings(stngs):
        c = Collaborator(stngs['host'])
        for k in ('port', 'name'):
            if stngs.has_key(k):
                setattr(c, k, stngs[k])
        return c

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
        Collaboration.instances[collab.id] = collab
        print('Registered {0}'.format(collab))
        if collab.isPending:
            sublime.set_timeout(lambda: Collaboration.remove_pending(collab.id), 5000)

    @staticmethod
    def remove_pending(id):
        if Collaboration.instances.has_key(id):
            c = Collaboration.instances[id]
            if c.isPending:
                sublime.message_dialog('Collaboration with {0} timed out'.format(c.name))
                del Collaboration.instances[id]

    @staticmethod
    def get(id, pending=False):
        if Server.get() is None:
            for c in Collaboration.instances.values():
                c.isDead = True
        if Collaboration.instances.has_key(id):
            c = Collaboration.instances[id]
            if c.isDead:
                del Collaboration.instances[id]
            else:
                if not c.isPending or pending:
                    return c

    @staticmethod
    def recv(data):
        """
        Receive data from the Server and distribute it
        to the proper Collaboration
        """
        host = data['fromhost']
        fromid = data['fromid']
        id = data['toid']
        print('Collaboration.recv receiving data from {0}-{1} for view {2}'.format(host, fromid, id))
        c = Collaboration.get(id, pending=True)
        if c:
            c.recv_data(data)
            return
        print('Collaboration.recv no appropriate collaboration to receive data')

    @staticmethod
    def recv_start_request(data):
        """
        Receive and prompt the user with a collaboration request.
        """
        name = data['fromname']
        host = data['fromhost']
        port = data['fromport']
        accept = sublime.ok_cancel_dialog('{0} wishes to collaborate, continue?'.format(name))
        if accept:
            v = sublime.active_window().new_file()
            e = v.begin_edit()
            v.insert(e, 0, data['contents'])
            v.end_edit(e)
        # setup new collaboration
        c = Collaboration(v, host, port, remoteid=data['fromid'])
        c.isPending = False
        c.start()
        # build start response
        data = dict(
            type='startresponse',
            accept=accept,
        )
        c.send_data(data)

    @staticmethod
    def recv_start_response(data):
        """
        Receive a start request response and pass it off to the requesting collaboration.
        """
        if Collaboration.pending.has_key(data['id']):
            c = Collaboration.pending[data['id']]
            c.recv_start_response(data)

    @staticmethod
    def kill(id):
        c = Collaboration.get(id, pending=True)
        if c:
            c.isDead = True


    def __init__(self, view, remotehost, remoteport, remotename=None, remoteid=None):
        self.view = view
        self.remotehost = remotehost
        self.remoteport = remoteport
        self.remotename = remotename
        self.remoteid = remoteid
        self.host = this_host()
        self.port = Server.get().port
        self.name = this_name()
        self.isPending = True
        self.socket = None
        self.isDead = False
        print('created collaboration: {0}'.format(self))
        Collaboration.register(self)

    def __repr__(self):
        return '<Collaboration {0.id}, {0.remoteid}, {0.remotehost}, {0.remoteport}>'.format(self)

    def __del__(self):
        self.close()

    @property
    def remoteport(self):
        return self._remoteport
    @remoteport.setter
    def remoteport(self, value):
        self._remoteport = DEFAULT_PORT
        try:
            self._remoteport = int(value)
        except:
            pass

    @property
    def remotehost(self):
        return self._remotehost
    @remotehost.setter
    def remotehost(self, value):
        self._remotehost = value
        try:
            self._remotehost = socket.gethostbyname(value)
        except Exception as e:
            print('could not resolve host: {0}'.format(e))

    @property
    def id(self):
        return self.view.id()

    @property
    def view_contents(self):
        r = sublime.Region(0, self.view.size())
        return self.view.substr(r)

    @property
    def file_name(self):
        f = self.view.file_name()
        if f is None:
            f = 'new file'
        return f

    @property
    def is_connected(self):
        return self.socket is not None

    def connect(self):
        """
        Attempt to connect to the host.
        If the connection fails the Collaboration will
        not be registered and die.
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.remotehost, self.remoteport))
        except socket.error, (value, message):
            sublime.status_message('Collaboration Error: {0}'.format(message))
            self.close()
            self.isDead = True
        else:
            print('collaboration socket connected: {0}'.format(self.remotehost))

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
        If the collaboration is refused it will die.

        If a remoteid is already established, the collaboration does
        not need to send a starting request and simply registers itself.
        """
        self.connect()
        if self.is_connected:
            if not self.remoteid:
                self.send_start_request()

    def send_start_request(self):
        """
        Send a collaboration start request to the remote host.
        """
        data = dict(
            type='start',
            fromname=self.name,
            contents=self.view_contents,
        )

        self.view.set_status('collab_start', 'waiting for {0} to start collaboration'.format(self.remotename))
        sublime.status_message('Starting collaboration on {0} with {1}'.format(self.file_name, self.remotename))
        self.send_data(data)

    def recv_start_response(self, data):
        """
        Receive a response to a sent collaboration start request.
        """
        accepted = int(data['accept'])
        self.remoteid = int(data['fromid'])
        self.remotehost = data['fromhost']
        self.view.erase_status('collab_start')
        if accepted:
            sublime.status_message('Collaboration with {0} established'.format(self.remotename))
            self.isPending = False
        else:
            Collaboration.remove_pending(self.id)


    def send_command(self, cmd, sel=None):
        data = dict( type='cmd', cmd=cmd[0], args=cmd[1], sel=sel )
        self.send_data(data)

    def recv_command(self, data):
        cmd = data['cmd']
        args = data['args']
        sel = data['sel']
        print(cmd, args, sel)
        #self.view.run_command(cmd, args)
        # TODO: handle selection changes....

    def send_data(self, data):
        data = data.copy()
        data.update(dict(
            fromhost=self.host,
            fromport=self.port,
            fromid=self.id,
            toid=self.remoteid)
        )
        print('sending data from {0.host}-{0.id} to {0.remotehost}-{0.remoteid}: {1}'.format(self, data))
        msg = ClientMessage(self.socket, data)
        msg.start()
        self.handle_messages([msg])

    def recv_data(self, data):
        """
        Receive data passed to this Collaboration by the server.
        This will usually represent edit commands or the like.
        """
        print('{0} received data: {1}'.format(self, data))
        # start requests dont come through the collaboration
        # because it doesnt exist yet. the Server handles that
        if data['type'] == 'startresponse':
            self.recv_start_response(data)
        elif data['type'] == 'cmd':
            self.recv_command(data)

    def handle_messages(self, msgs):
        remaining = []
        for m in msgs:
            if m.is_alive():
                remaining.append(m)
                continue
            if m.success == False:
                sublime.status_message('Collaboration Error: {0}'.format(m.error))
                continue
            self.handle_response(m)
        msgs = remaining
        # check if we have msgs left to handle
        if len(msgs):
            self.view.set_status('collab', 'collab: {0} pending msg(s)'.format(len(msgs)))
            sublime.set_timeout(lambda: self.handle_messages(msgs), 20)
        self.view.erase_status('collab')

    def handle_response(self, msg):
        """
        Handle the immediate responses from a sent message.
        This is not the same as handling incoming data messages.
        """
        pass

class Server(object):
    instance = None

    @staticmethod
    def start():
        if Server.instance is None:
            s = Server()
            s.run()
            Server.instance = s
            if s.is_connected:
                print('Collaboration Server Started')

    @staticmethod
    def stop():
        if Server.instance is not None:
            Server.instance.quit = True
            Server.instance = None

    @staticmethod
    def get():
        return Server.instance

    @staticmethod
    def recv(data):
        Server.instance.recv_data(data)

    def __init__(self):
        self.host = ''
        self.port = DEFAULT_PORT
        self.size = DEFAULT_SIZE
        self.backlog = 5
        self.listener = None
        self.server = None
        self.quit = False
        self.threads = []

    @property
    def is_connected(self):
        return self.server is not None

    def open(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.bind((self.host, self.port))
            self.server.listen(self.backlog)
        except socket.error, (value, message):
            self.close()
            print('could not open server socket: {0}'.format(message))
        else:
            print('server started: {0}'.format(self.server.getsockname()))

    def close(self):
        if self.server:
            self.server.close()
            print('Collaboration Server Stopped')
        self.server = None

    def run(self):
        self.open()
        if self.server:
            print('server running')
            self.recv_input()

    def recv_input(self):
        inputready, outputready, exceptready = select.select([self.server],[],[], 0.05)

        for s in inputready:
            if s == self.server:
                print('makin a receiver')
                cr = ClientReceiver(self.server.accept())
                cr.start()
                self.threads.append(cr)

        for cr in self.threads:
            if not cr.is_alive():
                print('attempting to join a receiver')
                cr.join()
                self.threads.remove(cr)

        if self.quit:
            print('waiting for threads to finish...')
            for c in self.threads:
                c.join()
            self.close()
            return

        sublime.set_timeout(self.recv_input, 500)

    def recv_data(self, data):
        print('server received data: {0}'.format(data))
        if data is None:
            return
        if isinstance(data, basestring):
            try:
                data = eval(data)
            except:
                print('server received bad data')
                return
        if data['type'] == 'start':
            Collaboration.recv_start_request(data)
        else:
            Collaboration.recv(data)


class ServerListener(threading.Thread):
    def __init__(self, server):
        threading.Thread.__init__(self)
        self.server = server

    def run(self):
        run = True
        while run:
            inputready,outputready,exceptready = select.select(input,[],[])

            for s in inputready:
                if s == self.server:
                    # handle the server socket
                    c = Client(self.server.accept())
                    c.start()
                    self.threads.append(c)

        main_thread(Server.stop)


class ClientReceiver(threading.Thread):
    def __init__(self, (client, address), size=DEFAULT_SIZE): 
        threading.Thread.__init__(self)
        self.client = client
        self.address = address
        self.size = size
        self.data = None

    def run(self):
        self.data = self.client.recv(self.size)
        main_thread(Server.recv, self.data)
        # rspdata = {}
        # self.client.send(str(rspdata))
        self.client.close()
                


class ClientMessage(threading.Thread):
    def __init__(self, socket, data, size=DEFAULT_SIZE, timeout=5):
        threading.Thread.__init__(self)
        self.socket = socket
        self.timeout = timeout
        self.size = size
        self.data = data
        self.success = None
        self.error = None
        self.response = None

    def run(self):
        if self.socket is None:
            print('ClientMessage.socket is None, data: {0}'.format(self.data))
            return
        try:
            datastr = str(self.data)
            if self.data['type'] != 'cmd':
                self.socket.send(datastr)
            # self.response = self.socket.recv(self.size)
            self.success = True
        except Exception as e:
            self.error = e
            self.success = False



