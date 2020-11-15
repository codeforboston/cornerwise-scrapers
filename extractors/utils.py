from os import path
import subprocess


LayerDir = "/opt/bin"
PdfInfo = path.join(LayerDir, "pdfinfo")
PdfToText = path.join(LayerDir, "pdftotext")

class pushback_iter(object):
    """An iterator that implements a pushback() method, allowing values to
be added back to the 'stack' after consideration.
    """
    def __init__(self, it):
        """
        :it: an iterable object
        """
        self.iterable = iter(it)
        self.pushed = deque()

    def pushback(self, v):
        self.pushed.append(v)

    def __iter__(self):
        return self

    def __next__(self):
        if self.pushed:
            return self.pushed.pop()
        return next(self.iterable)


def pdfinfo(path):
    return dict(re.findall(
        r"([\w ]+):\s+([^\n]*)\n",
        subprocess.check_output([PdfInfo, path])))

def pdf_to_text(pdf_path, out_file):
    args = [PdfToText, "-enc", "UTF-8", pdf_path]
    kwargs = {}
    if isinstance(out_file, str):
        args.append(out_file)
    else:
        args.append("-")
        kwargs["stdout"] = out_file

    subprocess.check_output(args, **kwargs)
