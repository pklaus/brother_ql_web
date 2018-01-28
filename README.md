## brother\_ql\_web

This is a web service to print labels on Brother QL label printers.

You need Python 3 for this software to work.

### Installation

Get the code:

    git clone https://github.com/pklaus/brother_ql_web.git

or download [the ZIP file](https://github.com/pklaus/brother_ql_web/archive/master.zip) and unpack it.

Install the requirements:

    pip install -r requirements.txt

In addition, `fontconfig` should be installed on your system. This package is pre-installed on many Linux distributions and you can use Homebrew to install it on your Mac.

### Startup

To start the server, run `./brother_ql_web.py`. Here's its command line interface:

    usage: brother_ql_web.py [-h] [--port PORT] [--loglevel LOGLEVEL]
                             [--font-folder FONT_FOLDER]
                             [--default-label-size DEFAULT_LABEL_SIZE]
                             [--default-orientation {standard,rotated}]
                             [--model {QL-500,QL-550,QL-560,QL-570,QL-580N,QL-650TD,QL-700,QL-710W,QL-720NW,QL-1050,QL-1060N}]
                             printer
    
    This is a web service to print labels on Brother QL label printers.
    
    positional arguments:
      printer               String descriptor for the printer to use (like
                            tcp://192.168.0.23:9100 or file:///dev/usb/lp0)
    
    optional arguments:
      -h, --help            show this help message and exit
      --port PORT
      --loglevel LOGLEVEL
      --font-folder FONT_FOLDER
                            folder for additional .ttf/.otf fonts
      --default-label-size DEFAULT_LABEL_SIZE
                            Label size inserted in your printer. Defaults to 62.
      --default-orientation {standard,rotated}
                            Label orientation, defaults to "standard". To turn
                            your text by 90°, state "rotated".
      --model {QL-500,QL-550,QL-560,QL-570,QL-580N,QL-650TD,QL-700,QL-710W,QL-720NW,QL-1050,QL-1060N}
                            The model of your printer (default: QL-500)

### Usage

Once it's running, access the web interface by opening the page with your browser.
If you run it on your local machine, go to <http://localhost:8013> (You can change
the default port 8013 using the --port argument).
You will then be forwarded by default to the interactive web gui located at */labeldesigner*.

All in all, the web server offers:

* a Web GUI allowing you to print your labels at */labeldesigner*,
* an API at */api/print/text/Your_Text?font_size=100&font_family=Minion%20Pro&font_style=Semibold*
  to print a label containing 'Your Text' with the specified font properties.

