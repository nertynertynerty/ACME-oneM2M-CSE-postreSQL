#
#	Logging.py
#
#	(c) 2020 by Andreas Kraft
#	License: BSD 3-Clause License. See the LICENSE file for further details.
#
#	Wrapper for the logging sub-system. It provides simpler access as well
#	some more usefull output rendering.
#

"""	Wrapper class for the logging subsystem. """

from __future__ import annotations
from enum import IntEnum
import traceback
import logging, logging.handlers, os, inspect, sys, datetime, time, threading
from queue import Queue
from typing import List, Any, Union
from logging import LogRecord


from rich import inspect as richInspect
from rich.logging import RichHandler
from rich.style import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.default_styles import DEFAULT_STYLES
from rich.theme import Theme
from rich.tree import Tree
from rich.table import Table
from rich.prompt import Prompt

from ..etc.Types import JSON
from ..helpers.BackgroundWorker import BackgroundWorker, BackgroundWorkerPool
from ..services.Configuration import Configuration

levelName = {
	logging.INFO :    'ℹ️  I',
	logging.DEBUG :   '🐞 D',
	logging.ERROR :   '🔥 E',
	logging.WARNING : '⚠️  W'
	# logging.INFO :    'INFO   ',
	# logging.DEBUG :   'DEBUG  ',
	# logging.ERROR :   'ERROR  ',
	# logging.WARNING : 'WARNING'
}


class LogLevel(IntEnum):
	INFO 	= logging.INFO
	DEBUG 	= logging.DEBUG
	ERROR 	= logging.ERROR
	WARNING = logging.WARNING
	OFF		= sys.maxsize

	def __str__(self) -> str:
		return self.name
	

	def next(self) -> LogLevel:
		"""	Return next log level. This cycles through the levels.
		"""
		return {
			LogLevel.DEBUG:		LogLevel.INFO,
			LogLevel.INFO:		LogLevel.WARNING,
			LogLevel.WARNING:	LogLevel.ERROR,
			LogLevel.ERROR:		LogLevel.OFF,
			LogLevel.OFF:		LogLevel.DEBUG,
		}[self]


class Logging:
	""" Wrapper class for the logging subsystem. This class wraps the 
		initialization of the logging subsystem and provides convenience 
		methods for printing log, error and warning messages to a 
		logfile and to the console.
	"""

	logger  						= None
	loggerConsole					= None
	logLevel:LogLevel				= LogLevel.INFO
	isInfo 							= False
	isWarn 							= False
	isDebug 						= False
	lastLogLevel:LogLevel			= None
	enableFileLogging				= True
	enableScreenLogging				= True
	stackTraceOnError				= True
	enableBindingsLogging			= True
	worker 							= None
	queue:Queue						= None

	queueMaxsize:int				= 5000		# max number of items in the logging queue. Might otherwise grow forever on large load

	_console:Console				= None
	_richHandler:ACMERichLogHandler	= None
	_handlers:List[Any] 			= None
	_logWorker:BackgroundWorker		= None

	terminalColor					= 'spring_green2'
	terminalStyle:Style				= Style(color=terminalColor)
	terminalStyleError:Style		= Style(color='red')


	@staticmethod
	def init() -> None:
		"""Init the logging system.
		"""

		if Logging.logger:
			return
		Logging.enableFileLogging 		= Configuration.get('logging.enableFileLogging')
		Logging.enableScreenLogging		= Configuration.get('logging.enableScreenLogging')
		Logging.stackTraceOnError		= Configuration.get('logging.stackTraceOnError')
		Logging.enableBindingsLogging	= Configuration.get('logging.enableBindingsLogging')
		

		Logging.logger					= logging.getLogger('logging')			# general logger
		Logging.loggerConsole			= logging.getLogger('rich')				# Rich Console logger
		Logging._console				= Console()								# Console object
		Logging._richHandler			= ACMERichLogHandler()
		
		Logging.setLogLevel(Configuration.get('logging.level'))					# Assign the initial log level

		# Add logging queue
		Logging.queue = Queue(maxsize=Logging.queueMaxsize)

		# List of log handlers
		Logging._handlers = [ Logging._richHandler ]
		#Logging._handlers = [ ACMERichLogHandler() ]

		# Log to file only when file logging is enabled
		if Logging.enableFileLogging:
			from ..services import CSE as CSE

			logpath = Configuration.get('logging.path')
			os.makedirs(logpath, exist_ok=True)# create log directory if necessary
			logfile = f'{logpath}/cse-{CSE.cseType.name}.log'
			logfp = logging.handlers.RotatingFileHandler(logfile,
														 maxBytes=Configuration.get('logging.size'),
														 backupCount=Configuration.get('logging.count'))
			logfp.setLevel(Logging.logLevel)
			logfp.setFormatter(logging.Formatter('%(levelname)s %(asctime)s %(message)s'))
			Logging.logger.addHandler(logfp) 
			Logging._handlers.append(logfp)

		# config the logging system
		logging.basicConfig(level=Logging.logLevel, format='%(message)s', datefmt='[%X]', handlers=Logging._handlers)

		# Start worker to handle logs in the background
		from ..helpers.BackgroundWorker import BackgroundWorkerPool
		Logging._logWorker = BackgroundWorkerPool.newActor(Logging.loggingActor, name='loggingWorker')
		Logging._logWorker.start()	# Yes, this could be in one line but the _logworker attribute may not be assigned yet before the 
									# actor callback is executed, and this might result in a None exception
	
	
	@staticmethod
	def finit() -> None:
		if Logging.queue:
			while not Logging.queue.empty():
				time.sleep(0.5)
		if Logging._logWorker:
			Logging._logWorker.stop()
		Logging.log('')


	@staticmethod
	def loggingActor() -> bool:
		while Logging._logWorker.running:
			level, msg, caller, thread = Logging.queue.get(block=True)
			if isinstance(msg, str):
				Logging.loggerConsole.log(level, f'{os.path.basename(caller.filename)}*{caller.lineno}*{thread.name:<10.10}*{str(msg)}')
			else:
				richInspect(msg, private=True, dunder=True)

		return True


	@staticmethod
	def log(msg:Any, stackOffset:int=None) -> None:
		"""Print a log message with level INFO. 
		"""
		Logging._log(logging.INFO, msg, stackOffset=stackOffset)


	@staticmethod
	def logDebug(msg:Any, stackOffset:int=None) -> None:
		"""Print a log message with level DEBUG. 
		"""
		Logging._log(logging.DEBUG, msg, stackOffset=stackOffset)


	@staticmethod
	def logErr(msg:Any, showStackTrace:bool=True, exc:Exception=None, stackOffset:int=None) -> None:
		"""	Print a log message with level ERROR. 
			`showStackTrace` indicates whether a stacktrace shall be logged together with the error
			as well.
		"""
		from ..services import CSE
		# raise logError event
		CSE.event.logError()	# type: ignore
		if exc:
			fmtexc = ''.join(traceback.TracebackException.from_exception(exc).format())
			Logging._log(logging.ERROR, f'{msg}\n\n{fmtexc}', stackOffset=stackOffset)
		elif showStackTrace and Logging.stackTraceOnError:
			strace = ''.join(map(str, traceback.format_stack()[:-1]))
			Logging._log(logging.ERROR, f'{msg}\n\n{strace}', stackOffset=stackOffset)
		else:
			Logging._log(logging.ERROR, msg, stackOffset=stackOffset)


	@staticmethod
	def logWarn(msg:Any, stackOffset:int=None) -> None:
		"""Print a log message with level WARNING. 
		"""
		from ..services import CSE as CSE
		# raise logWarning event
		CSE.event.logWarning() 	# type: ignore
		Logging._log(logging.WARNING, msg, stackOffset=stackOffset)


	@staticmethod
	def logWithLevel(level:int, message:Any, showStackTrace:bool=False, stackOffset:int=None) -> None:
		"""	Fallback log method when the `level` is a separate argument.
		"""
		# TODO add a parameter frame substractor to correct the line number, here and in In _log()
		# TODO change to match in Python10
		level == logging.DEBUG and Logging.logDebug(message, stackOffset=stackOffset)
		level == logging.INFO and Logging.log(message, stackOffset=stackOffset)
		level == logging.WARNING and Logging.logWarn(message, stackOffset=stackOffset)
		level == logging.ERROR and Logging.logErr(message, showStackTrace=showStackTrace, stackOffset=stackOffset)


	@staticmethod
	def _log(level:int, msg:Any, stackOffset:int=None) -> None:
		"""	Internally adding various information to the log output. The `stackOffset` is used to determine 
			the correct caller. It is set by a calling method in case the log information are re-routed.
		"""
		if Logging.logLevel <= level:
			# Queue a log message : (level, message, caller from stackframe, current thread)
			try:
				Logging.queue.put((level, msg, inspect.getframeinfo(inspect.stack()[2 if not stackOffset else 2+stackOffset][0]), threading.current_thread()))
			except Exception as e:
				# sometimes this raises an exception. Just ignore it.
				pass
	

	@staticmethod
	def console(msg:Union[str, Text, Tree, Table, JSON]='&nbsp;', nl:bool=False, nlb:bool=False, end:str='\n', plain:bool=False, isError:bool=False, isHeader:bool=False) -> None:
		"""	Print a message or object on the console.
		"""
		# if this is a header then call the method again with different parameters
		if isHeader:
			Logging.console(f'**{msg}**', nlb=True, nl=True)
			return

		style = Logging.terminalStyle if not isError else Logging.terminalStyleError
		if nlb:	# Empty line before
			Logging._console.print()
		if isinstance(msg, str):
			Logging._console.print(msg if plain else Markdown(msg), style=style, end=end)
		elif isinstance(msg, dict):
			Logging._console.print(msg, style=style, end=end)
		elif isinstance(msg, (Tree, Table, Text)):
			Logging._console.print(msg, style=style, end=end)
		if nl:	# Empty line after
			Logging._console.print()
	

	@staticmethod
	def consoleClear() -> None:
		"""	Clear the console screen.
		"""
		Logging._console.clear()
	

	@staticmethod
	def consolePrompt(prompt:str, nl:bool=True) -> str:
		"""	Read a line from the console. 
			Catch EOF (^D) and Keyboard Interrup (^C). In that case None is returned.
		"""
		answer = None
		try:
			answer = Prompt.ask(prompt, console=Logging._console)
			if nl:
				Logging.console()
		except KeyboardInterrupt as e:
			pass
		except Exception:
			pass
		return answer

	
	@staticmethod
	def inspect(obj:Any) -> None:
		Logging._log(Logging.logLevel, obj)


	@staticmethod
	def off() -> None:
		"""	Switch logging off. Remember the last logLevel
		"""
		if Logging.logLevel != LogLevel.OFF:
			Logging.lastLogLevel = Logging.logLevel
			Logging.setLogLevel(LogLevel.OFF)


	@staticmethod
	def on() -> None:
		"""	Switch logging on. Enable the last logLevel.
		"""
		if Logging.logLevel == LogLevel.OFF and Logging.lastLogLevel:
			Logging.setLogLevel(Logging.lastLogLevel)
			Logging.lastLogLevel = None
	

	@staticmethod
	def setLogLevel(logLevel:LogLevel) -> None:
		"""	Set a new log level to the logging system.
		"""
		Logging.logLevel = logLevel
		Logging.loggerConsole.setLevel(logLevel)

		# Set the is... indicators for optimizing the log output
		Logging.isDebug = Logging.logLevel <= LogLevel.DEBUG
		Logging.isInfo 	= Logging.logLevel <= LogLevel.INFO
		Logging.isWarn	= Logging.logLevel <= LogLevel.WARNING



#
#	Redirect handler to support Rich formatting
#

class ACMERichLogHandler(RichHandler):

	def __init__(self, level: int = logging.NOTSET, console: Console = None) -> None:

		# Add own styles to the default styles and create a new theme for the console
		ACMEStyles = { 
			'repr.dim' 				: Style(color='grey70', dim=True),
			'repr.request'			: Style(color='spring_green2'),
			'repr.response'			: Style(color='magenta2'),
			'repr.id'				: Style(color='light_sky_blue1'),
			'repr.url'				: Style(color='sandy_brown', underline=True),
			'repr.start'			: Style(color='orange1'),
			'logging.level.debug'	: Style(color='grey50'),
			'logging.level.warning'	: Style(color='orange3'),
			'logging.level.error'	: Style(color='red', reverse=True),
			'logging.console'		: Style(color='spring_green2'),
		}
		_styles = DEFAULT_STYLES.copy()
		_styles.update(ACMEStyles)

		super().__init__(level=level, console=Console(theme=Theme(_styles)))


		# Set own highlights 
		self.highlighter.highlights = [	# type: ignore
			# r"(?P<brace>[\{\[\(\)\]\}])",
			#r"(?P<tag_start>\<)(?P<tag_name>\w*)(?P<tag_contents>.*?)(?P<tag_end>\>)",
			#r"(?P<attrib_name>\w+?)=(?P<attrib_value>\"?\w+\"?)",
			#r"(?P<bool_true>True)|(?P<bool_false>False)|(?P<none>None)",
			r"(?P<none>None)",
			#r"(?P<id>(?<!\w)\-?[0-9]+\.?[0-9]*\b)",
			# r"(?P<number>\-?[0-9a-f])",
			r"(?P<number>\-?0x[0-9a-f]+)",
			#r"(?P<filename>\/\w*\.\w{3,4})\s",
			r"(?<!\\)(?P<str>b?\'\'\'.*?(?<!\\)\'\'\'|b?\'.*?(?<!\\)\'|b?\"\"\".*?(?<!\\)\"\"\"|b?\".*?(?<!\\)\")",
			#r"(?P<id>[\w\-_.]+[0-9]+\.?[0-9])",		# ID
			r"(?P<url>https?:\/\/[0-9a-zA-Z\$\-\_\~\+\!`\(\)\,\.\?\/\;\:\&\=\%]*)",
			#r"(?P<uuid>[a-fA-F0-9]{8}\-[a-fA-F0-9]{4}\-[a-fA-F0-9]{4}\-[a-fA-F0-9]{4}\-[a-fA-F0-9]{12})",

			# r"(?P<dim>^[0-9]+\.?[0-9]*\b - )",			# thread ident at front
			r"(?P<dim>^[^ ]*[ ]*- )",						# thread ident at front
			r"(?P<request>==>.*:)",							# Incoming request or response
			r"(?P<request>[^-]+Request ==>:)",				# Outgoing request or response
			r"(?P<response><== [^:]+[(:]+)",				# outgoing response or request
			r"(?P<response>[^-]+Response <== [^ :]+[ :]+)",		# Incoming response or request
			r"(?P<number>\(RSC: [0-9]+\.?[0-9]\))",			# Result code
			#r"(?P<id> [\w/\-_]*/[\w/\-_]+)",				# ID
			r"(?P<number>\nHeaders: )",
			r"(?P<number> \- Headers: )",
			r"(?P<number>\nBody: )",
			r"(?P<number> \- Body: )",
			r"(?P<number> \- Operation: )",
			# r"(?P<request>CSE started$)",					# CSE startup message
			# r"(?P<request>CSE shutdown$)",					# CSE shutdown message
			# r"(?P<start>CSE shutting down$)",				# CSE shutdown message
			# r"(?P<start>Starting CSE$)",				# CSE shutdown message

			#r"(?P<id>(acp|ae|bat|cin|cnt|csest|dvi|grp|la|mem|nod|ol|sub)[0-9]+\.?[0-9])",		# ID

		]
		
	def emit(self, record:LogRecord) -> None:
		"""	Invoked by logging. """
		if not Logging.enableScreenLogging or record.levelno < Logging.logLevel:
			return
		if record.name == 'werkzeug':	# filter out werkzeug's loggings
			return
		#path = Path(record.pathname).name
		
		message	= self.format(record)
		if len(messageElements := message.split('*', 3)) == 4:
			path 	= messageElements[0]
			lineno 	= int(messageElements[1])
			threadID= messageElements[2]
			message = messageElements[3]
		else:
			path	= ''
			lineno	= 0
			threadID= ''

		self.console.print(
			self._log_render(
				self.console,
				[ self.highlighter(Text(f'{threadID} - {message}')) ],
				log_time	= datetime.datetime.fromtimestamp(record.created),
				# time_format	= None if self.formatter is None else self.formatter.datefmt,
				time_format	= self.formatter.datefmt,
				level		= Text(f'{record.levelname:<7}', style=f'logging.level.{record.levelname.lower()}'),
				path		= path,
				line_no		= lineno,
			)
		)
