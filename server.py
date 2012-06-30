#!/usr/bin/env python 

import select
import socket
import sys
import threading

class Server:
	def __init__(self):
		self.host = ''
		self.port = 50000
		self.backlog = 5
		self.size = 1024
		self.server = None
		self.threads = []

	def open_socket(self):
		try:
			self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.server.bind((self.host,self.port))
			self.server.listen(5)
		except socket.error, (value,message):
			if self.server:
				self.server.close()
			print "Could not open socket: " + message
			sys.exit(1)
		else:
			print('opened server: {0}'.format(self.server.getsockname()))

	def run(self):
		print('server running')
		self.open_socket()
		input = [self.server, sys.stdin]
		running = 1
		while running:
			inputready,outputready,exceptready = select.select(input,[],[])

			for s in inputready:

				if s == self.server:
					# handle the server socket
					c = Client(self.server.accept())
					c.start()
					self.threads.append(c)

				elif s == sys.stdin:
					junk = sys.stdin.readline()
					print('stdin: {0!r}'.format(junk))
					# handle standard input
					running = 0

		# close all threads
		self.server.close()
		print('waiting for clients to quit...')
		for c in self.threads:
			c.join()
		print('server closed')


class Client(threading.Thread): 
	def __init__(self,(client,address)): 
		threading.Thread.__init__(self) 
		self.client = client 
		self.address = address 
		self.size = 1024 
	def run(self):
		running = 1
		while running:
			data = self.client.recv(self.size)
			if data:
				print('received: {0!r}'.format(data))
				self.client.send(data)
			else:
				self.client.close()
				running = 0

if __name__ == "__main__":
	s = Server()
	s.run()

