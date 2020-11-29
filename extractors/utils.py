from os import path
import re
import subprocess


LayerDir = "/opt/bin"
PdfInfo = path.join(LayerDir, "pdfinfo")
PdfToText = path.join(LayerDir, "pdftotext")


DefaultExtractOpts = {
    "marginb": 65,
    "margint": 65,
    "marginl": 65,
    "marginr": 65,
}

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

def parse_pdf_dims(dims):
    m = re.match(r"(\d+) x (\d+) pt", dims)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    return (None, None)

def pdfinfo(path):
    return dict(re.findall(
        r"([\w ]+):\s+([^\n]*)\n",
        subprocess.check_output([PdfInfo, path]).decode()))

def pdf_dims(path):
    info = pdfinfo(path)
    return parse_pdf_dims(info["Page size"])

def prepare_pdfextract_args(opts, dims=None):
    if dims:
        [x, y, b, r] = [opts.get(f"margin{k}", 0) for k in ["l", "t", "b", "r"]]
        if x+y+b+r:
            (w, h) = dims
            opts.update({
                "x": x,
                "y": y,
                "W": w-r-x,
                "H": h-b-y,
            })

    return sum([[f"-{kopt}"] if v is True else [f"-{kopt}", str(v)]
                for kopt, v in opts.items() if not kopt.startswith("margin")], [])

def pdf_to_text(pdf_path, out_file, extra_opts=DefaultExtractOpts):
    opts = { "enc": "UTF-8" }
    opts.update(extra_opts)

    args = [PdfToText, *prepare_pdfextract_args(opts)]
    kwargs = {}
    if isinstance(out_file, str):
        args.append(out_file)
    else:
        args.append("-")
        kwargs["stdout"] = out_file

    subprocess.check_output(args, **kwargs)
