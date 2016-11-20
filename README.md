### brother\_ql\_web

This is a web service to print labels on Brother QL label printers.

It offers:
* an API at */api/print/text/Your_Text?font_size=100&font_family=Minion%20Pro&font_style=Semibold*
  to print a label containing 'Your Text' with the specified font properties.

You need Python 3 for this software to work.

#### Installation

Get the code:

    git clone https://github.com/pklaus/brother_ql_web.git

or download [the ZIP file](https://github.com/pklaus/brother_ql_web/archive/master.zip) and unpack it.

Install the requirements:

    pip install -r requirements.txt

#### Usage

To start the server, run `./brother_ql_web.py`. Here's its command line interface:

    usage: brother_ql_web.py [-h] [--port PORT] [--loglevel LOGLEVEL]
                             [--font-folder FONT_FOLDER]
                             [--model {QL-500,QL-550,QL-560,QL-570,QL-580N,QL-650TD,QL-700,QL-710W,QL-720NW,QL-1050,QL-1060N}]
                             printer
    
    positional arguments:
      printer               String descriptor for the printer to use (like
                            tcp://192.168.0.23:9100 or file:///dev/usb/lp0)
    
    optional arguments:
      -h, --help            show this help message and exit
      --port PORT
      --loglevel LOGLEVEL
      --font-folder FONT_FOLDER
                            folder for additional .ttf/.otf fonts
      --model {QL-500,QL-550,QL-560,QL-570,QL-580N,QL-650TD,QL-700,QL-710W,QL-720NW,QL-1050,QL-1060N}
                            The model of your printer (default: QL-500)
