import base64
import os


class Pipe:
    def __init__(self):
        self.fd_read = -1
        self.fd_write = -1

    def open(self):
        if self.fd_read >= 0 or self.fd_write >= 0:
            raise RuntimeError('pipe is already open')
        self.fd_read, self.fd_write = os.pipe()

    def close(self):
        if self.fd_read >= 0:
            os.close(self.fd_read)
            self.fd_read = -1
        if self.fd_write >= 0:
            os.close(self.fd_write)
            self.fd_write = -1

    def __del__(self):
        self.close()

    def swap_read(self, pipe):
        self.fd_read, pipe.fd_read = pipe.fd_read, self.fd_read

    def write(self, data):
        if self.fd_write < 0:
            raise RuntimeError('pipe is not open')
        os.write(self.fd_write, data)

    def read(self, size):
        if self.fd_read < 0:
            raise RuntimeError('pipe is not open')
        return os.read(self.fd_read, size)

    def fds(self):
        return self.fd_read, self.fd_write


class Fzfy:
    def __init__(self):
        self.process = None
        self.pipe = None
        self.data = []

    def __enter__(self):
        import subprocess
        if self.process is not None or self.pipe is not None:
            raise RuntimeError('fzf is already running')
        try:
            self.pipe = Pipe()
            self.pipe.open()
            pipe_fzf = Pipe()
            try:
                pipe_fzf.open()
                pipe_fzf.swap_read(self.pipe)
                rd, wr = pipe_fzf.fds()
                command = [
                    'fzf',
                    '--with-nth=2..',
                    '--preview',
                    ' && '.join([
                        f'echo {{}} >&{pipe_fzf.fd_write}',
                        f'read -r -u {pipe_fzf.fd_read} data',
                        'exec base64 -d <<<"$data"',
                    ]),
                ]
                self.process = subprocess.Popen(command,
                                                stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE,
                                                pass_fds=(rd, wr))
            finally:
                del pipe_fzf
        except Exception:
            try:
                self.__del__()
            except Exception:
                pass
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__del__()

    def __del__(self):
        if self.pipe is not None:
            del self.pipe
            self.pipe = None
        if self.process is not None:
            if self.process.stdin is not None:
                self.process.stdin.close()
            if self.process.stdout is not None:
                self.process.stdout.close()
            self.process.kill()
            self.process.wait()
            self.process = None

    def lines_add(self, line, preview=None):
        if self.process is None or self.process.stdin is None:
            raise RuntimeError('fzf is not running')
        i = len(self.data)
        self.data.append(preview)
        data = f'{i} {line}\n'.encode('utf-8')
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def lines_close(self):
        if self.process is None or self.process.stdin is None:
            return
        self.process.stdin.close()

    def wait(self):
        if self.process is None or self.pipe is None:
            raise RuntimeError('fzf is not running')
        self.lines_close()
        while True:
            selection = self.pipe.read(8192)
            if not selection:
                break
            try:
                i, _ = selection.decode('utf-8').split(maxsplit=1)
                reply = self.data[int(i)]
            except Exception:
                reply = ''
            line = (base64.b64encode(reply.encode('utf-8')).decode('utf-8') + '\n').encode('utf-8')
            self.pipe.write(line)
        self.pipe.close()
        if self.process.stdout is not None:
            i, selection = self.process.stdout.read().decode('utf-8').split(maxsplit=1)
            selection = selection.rstrip('\n')
            self.process.stdout.close()
        else:
            selection = None
        rc = self.process.wait()
        return rc, selection
