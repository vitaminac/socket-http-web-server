# coding=utf-8

import socket
import struct
import sys
import threading
from email.utils import formatdate
from io import BufferedIOBase
from urllib.parse import unquote, urlparse

from qsonac.response import Response
from qsonac.status_codes import codes as status_codes


class _SocketWriter(BufferedIOBase):
    """Simple writable BufferedIOBase implementation for a socket

    Does not hold data in a buffer, avoiding any need to call flush()."""

    def __init__(self, sock):
        self._sock = sock

    def writable(self):
        return True

    def write(self, b):
        self._sock.sendall(b)
        with memoryview(b) as view:
            return view.nbytes

    def fileno(self):
        return self._sock.fileno()


def makeWSGIhandler(wsgi_app):
    class WSGIRequestHandler():
        """A request handler that implements WSGI dispatching."""
        """
        HTTP request handler base class.

        This class is instantiated for each request to be handled.
        The constructor sets the instance variables request, client_address
        and server, and then calls the handle() method.
        """

        # from factory function makeWSGIhandler
        app = wsgi_app

        # Define self.rfile and self.wfile for stream sockets.

        # Default buffer sizes for rfile, wfile.
        # We default rfile to buffered because otherwise it could be
        # really slow for large data (a getc() call per byte); we make
        # wfile unbuffered because (a) often after a write() we want to
        # read and we need to flush the line; (b) big writes to unbuffered
        # files are typically optimized by stdio even when big reads
        # aren't.
        rbufsize = -1
        wbufsize = 0

        # A timeout to apply to the request socket, if not None.
        timeout = None
        _timeout = 1500
        recv_timeout = struct.pack('LL', _timeout, 0)
        # Disable nagle algorithm for this socket, if True.
        # Use only when wbufsize != 0, to avoid small packets.
        disable_nagle_algorithm = False

        """
        HTTP (HyperText Transfer Protocol) is an extensible protocol on
        top of a reliable stream transport (e.g. TCP/IP).  The protocol
        recognizes three parts to a request:
    
        1. One line identifying the request type and path
        2. An optional set of RFC-822-style headers
        3. An optional data part
        
        The headers and data are separated by a blank line.

        The first line of the request has the form

        <command> <path> <version>
        
        where <command> is a (case-sensitive) keyword such as GET or POST,
        <path> is a string containing path information for the request,
        and <version> should be the string "HTTP/1.0" or "HTTP/1.1".
        <path> is encoded using the URL encoding scheme (using %xx to signify
        the ASCII character with hex code xx).
        
        The specification specifies that lines are separated by CRLF but
        for compatibility with the widest range of clients recommends
        servers also handle LF.  Similarly, whitespace in the request line
        is treated sensibly (allowing multiple spaces between components
        and allowing trailing whitespace).
        
        Similarly, for output, lines ought to be separated by CRLF pairs
        but most clients grok LF characters just fine.
    
        If the first line of the request has the form
    
        <command> <path>
    
        (i.e. <version> is left out) then this is assumed to be an HTTP
        0.9 request; this form has no optional headers and data part and
        the reply consists of just the data.
        
        The reply form of the HTTP 1.x protocol again has three parts:

        1. One line giving the response code
        2. An optional set of RFC-822-style headers
        3. The data
        
        Again, the headers and data are separated by a blank line.
    
        The response code line has the form
    
        <version> <responsecode> <responsestring>
        
        where <version> is the protocol version ("HTTP/1.0" or "HTTP/1.1"),
        <responsecode> is a 3-digit response code indicating success or
        failure of the request, and <responsestring> is an optional
        human-readable string explaining what the response code means.
        
        This server parses the request and the headers, and then calls a
        function specific to the request type (<command>).  Specifically,
        a request SPAM will be handled by a method do_SPAM().  If no
        such method exists the server sends an error response to the
        client.  If it exists, it is called with no arguments:
        
        do_SPAM()

        Note that the request name is case sensitive (i.e. SPAM and spam
        are different requests).
    
        The various request details are stored in instance variables:
    
        - client_address is the client IP address in the form (host,
        port);
    
        - command, path and version are the broken-down request line;
    
        - headers is an instance of email.message.Message (or a derived
        class) containing the header information;
    
        - rfile is a file object open for reading positioned at the
        start of the optional input data part;
    
        - wfile is a file object open for writing.
        
        IT IS IMPORTANT TO ADHERE TO THE PROTOCOL FOR WRITING!

        The first thing to be written must be the response line.  Then
        follow 0 or more header lines, then a blank line, and then the
        actual data (if any).  The meaning of the header lines depends on
        the command executed by the server; in most cases, when data is
        returned, there should be at least one header line of the form
    
        Content-type: <type>/<subtype>
    
        where <type> and <subtype> should be registered MIME types,
        e.g. "text/html" or "text/plain".
        """

        __version__ = "0.9"

        error_message_format = """\
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"
        "http://www.w3.org/TR/html4/strict.dtd">
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html;charset=utf-8">
        <title>Error response</title>
    </head>
    <body>
        <h1>Error response</h1>
        <p>Error code: %(code)d</p>
        <p>Message: %(message)s.</p>
        <p>Error code explanation: %(code)s - %(explain)s.</p>
    </body>
</html>
"""
        error_content_type = "text/html;charset=utf-8"

        # The default request version.  This only affects responses up until
        # the point where the request line is parsed, so it mainly decides what
        # the client gets back when sending a malformed request line.
        # Most web servers default to HTTP 0.9, i.e. don't send a status line.
        default_request_version = "HTTP/0.9"
        default_response_version = "HTTP/1.1"

        # maximal line length when calling readline().
        Max_Bytes_Per_Line_Field = 65536

        Max_Headers = 30
        """A request handler that implements WSGI dispatching."""

        # The server software version.  You may want to override this.
        # The format is multiple whitespace-separated strings,
        # where each string is of the form name[/version].
        server_version = "Simple HTTP/" + __version__

        http_head_encoding = "iso-8859-1"

        def __init__(self, request, client_address, server, debug: bool = False):
            self.debug = True
            self.request = request
            self.client_address = client_address
            self._server = server
            self.request = request
            self.client_address = client_address
            self.log("handler created for")
            self.response_head_buffer = { "status": "", "headers": { } }
            # self.server = server
            self.setup()
            try:
                self.log("start handle ")
                self.handle()
            except (socket.timeout, TimeoutError) as e:
                self.send_error(408, str(e))
            except Exception as e:
                self.log("error happened during processing ", e)
                import traceback
                traceback.print_exc()
            finally:
                self.finish()

        @property
        def server(self):
            return self._server

        def log(self, msg, *args):
            print(threading.current_thread(), ":", msg, self.request, "from", self.client_address, sep="")
            if args:
                print("more info", args, sep="")
            print()

        def make_environ(self):
            request_url = urlparse(self.path)
            url_scheme = 'https' if hasattr(self.server, "sslcontext") and self.server.ssl_context else 'http'
            environ = {
                'REQUEST_METHOD'   : self.command,
                'SCRIPT_NAME'      : '',
                'PATH_INFO'        : self.path,
                'QUERY_STRING'     : '',
                'SERVER_NAME'      : self.server.host,
                'SERVER_PORT'      : self.server.port,
                'SERVER_PROTOCOL'  : self.request_version,
                'wsgi.version'     : (1, 0),
                'wsgi.url_scheme'  : url_scheme,
                'wsgi.input'       : self.rfile,
                'wsgi.errors'      : sys.stderr,
                "wsgi.multithread" : self.server.multithread,
                "wsgi.multiprocess": self.server.multiprocess,
                'SERVER_SOFTWARE'  : self.server_version,
                'REMOTE_ADDR'      : self.client_address[0],
                'REMOTE_PORT'      : self.client_address[1],
            }
            for key, value in self.headers.items():
                key = key.upper().replace('-', '_')
                if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                    key = 'HTTP_' + key
                environ[key] = value

            if request_url.scheme and request_url.netloc:
                environ['HTTP_HOST'] = request_url.netloc

            self.log("environ created", environ)

            return environ

        def setup(self):
            self.connection = self.request
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, self.recv_timeout)
            self.connection.settimeout(self.timeout)
            if self.disable_nagle_algorithm:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            self.rfile = self.connection.makefile('rb', self.rbufsize)
            self.wfile = _SocketWriter(self.connection)

        def finish(self):
            self.log("completed handling")
            self.wfile.close()
            self.rfile.close()

        def send_error(self, code: int, message: str = "error occured", explain = None):
            if self.debug:
                self.write_itr(Response(code, message))

        def parse_headers(self, fp):
            """Parses only RFC2822 headers from a file pointer.

            email Parser wants to see strings rather than bytes.
            But a TextIOWrapper around self.rfile would buffer too many bytes
            from the stream, bytes which we later need to read as bytes.
            So we read the correct bytes here, as bytes, for email Parser
            to parse.

            """
            headers = []
            for i in range(self.Max_Headers):
                line = fp.readline(self.Max_Bytes_Per_Line_Field).decode(self.http_head_encoding)
                headers.append(line)
                if line in ('\r\n', '\n', ''):
                    break
            return dict([(s[0], "".join(s[1:])) for s in ([header.strip().split(":") for header in headers])])

        def parse_request(self):
            """Parse a request (internal)."""
            """
                The request should be stored in self.raw_requestline; the results
                are in self.command, self.path, self.request_version and
                self.headers.
    
                Return True for success, False for failure; on failure, an
                error is sent back.
            """
            self.requestline = str(self.raw_requestline, self.http_head_encoding).rstrip('\r\n')
            # Examine the headers and look for a Connection directive.
            # RFC 2145 section 3.1 says there can be only one "." and
            #   - major and minor numbers MUST be treated as
            #      separate integers;
            #   - HTTP/2.4 is a lower version than HTTP/2.13, which in
            #      turn is lower than HTTP/12.3;
            #   - Leading zeros MUST be ignored by recipients.
            self.command, self.path, self.request_version = self.requestline.split()
            self.path = unquote(self.path)
            if self.request_version[:5] != 'HTTP/':
                raise ValueError
            self.headers = self.parse_headers(self.rfile)
            self.log("request headers parsed", self.headers)
            try:
                conntype = self.headers["Connection"]
                if conntype.lower() == 'close':
                    self.close_connection = not conntype.lower() == 'keep-alive'
            except KeyError:
                self.close_connection = True

        def handle_request(self):
            if self.headers.get('Expect', '').lower().strip() == '100-continue':
                self.wfile.write(b'HTTP/1.1 100 Continue\r\n\r\n')
            self.log("try to run wsgi app")
            self.run_wsgi(wsgi_app)

        def handle(self):
            '''
            The handle() method can find the request as self.request, the
            client address as self.client_address, and the server (in case it
            needs access to per-server information) as self.server.  Since a
            separate instance is created for each request, the handle() method
            can define other arbitrary instance variables.
            :return:
            :rtype:
            '''
            """
                Handle a single HTTP request.

                You normally don't need to override this method; see the class
                __doc__ string for information on how to handle specific HTTP
                commands such as GET and POST.
                
            """
            self.log("try to read http head line from ")
            self.raw_requestline = self.rfile.readline(self.Max_Bytes_Per_Line_Field)
            if self.raw_requestline:
                if len(self.raw_requestline) < self.Max_Bytes_Per_Line_Field:
                    self.log("try to parse request head")
                    self.parse_request()
                    self.handle_request()
                else:
                    # 414 - 'Request-URI Too Long'
                    self.send_error(status_codes["414"])

        def write(self, data):
            if data:
                if hasattr(self, "response_head_buffer") and self.response_head_buffer:
                    buffer = [self.response_head_buffer["status"]] + [('%s: %s\r\n' % header) for header in self.response_head_buffer["headers"].items()] + ["\r\n"]
                    http_head = "".join(buffer).encode(self.http_head_encoding)
                    self.log("try to send response head", http_head)
                    self.wfile.write(http_head)
                    # del such buffer, if application intent to reset header will raise exception in start response
                    del self.response_head_buffer
                self.log("try to send to", data)
                self.wfile.write(data)

        def write_itr(self, itr):
            try:
                for chunk in itr:
                    self.write(chunk)
            finally:
                itr.close()

        def run_wsgi(self, app):
            """
            some point that doesnt implement according to PEP 3333,
            1. not check exc_info in start_response if application try to modify already set status or headers
            2. doesn't guarantee to yield only n bytes specify in content-length
            3. doesn't guarantee a line-end like in request body

            :param app:
            :type app:
            :return: None
            :rtype: None
            """

            # this could be called more than once
            def start_response(status, response_headers, exc_info = None):
                headers = dict([(key.capitalize(), value) for key, value in response_headers])
                if 'Content-length' not in headers:
                    headers["Connection"] = "close"
                if 'Server' not in headers:
                    # A name for the server
                    headers['Server'] = self.server.version
                if 'Date' not in headers:
                    # The date and time that the message was sent (in "HTTP-date" format as defined by RFC 7231
                    headers['Date'] = formatdate(timeval=None, localtime=False, usegmt=True)
                # will raise exception if try reset headers after it has already been sent
                self.response_head_buffer["status"] = f"{self.request_version} {status}\r\n"
                self.response_head_buffer["headers"] = headers
                exc_info = None  # Avoid circular
                return self.write

            def execute(app):
                self.environ = self.make_environ()
                app_itr = app(self.environ, start_response)
                self.write_itr(app_itr)

            execute(app)

    return WSGIRequestHandler
