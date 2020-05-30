#
#	SUB.py
#
#	(c) 2020 by Andreas Kraft
#	License: BSD 3-Clause License. See the LICENSE file for further details.
#
#	ResourceType: Subscription
#

import random, string
from Constants import Constants as C
import Utils, CSE
from .Resource import *

# TODO Attribute validations

# LIMIT: Only http(s) requests in nu or POA is supported yet

class SUB(Resource):

	def __init__(self, jsn=None, pi=None, create=False):
		super().__init__(C.tsSUB, jsn, pi, C.tSUB, create=create)

		if self.json is not None:
			self.setAttribute('nct', C.nctAll, overwrite=False) # LIMIT TODO: only this notificationContentType is supported now
			self.setAttribute('enc/net', [ C.netResourceUpdate ], overwrite=False)


# TODO expirationCounter
# TODO notificationForwardingURI
# TODO subscriberURI

	# Enable check for allowed sub-resources
	def canHaveChild(self, resource):
		return super()._canHaveChild(resource, [])


	def activate(self, parentResource, originator):
		if not (result := super().activate(parentResource, originator))[0]:
			return result
		return CSE.notification.addSubscription(self, originator)
		# res = CSE.notification.addSubscription(self, originator)
		# return (res, C.rcOK if res else C.rcTargetNotSubscribable)


	def deactivate(self, originator):
		super().deactivate(originator)
		return CSE.notification.removeSubscription(self)


	def update(self, jsn, originator):
		(res, rc) = super().update(jsn, originator)
		if not res:
			return (res, rc)
		return CSE.notification.updateSubscription(self)
		# res = CSE.notification.updateSubscription(self)
		# return (res, C.rcOK if res else C.rcTargetNotSubscribable)
 

	def validate(self, originator, create=False):
		if (res := super().validate(originator, create))[0] == False:
			return res
		Logging.logDebug('Validating subscription: %s' % self['ri'])

		# Check necessary attributes
		if (nu := self['nu']) is None or not isinstance(nu, list):
			Logging.logDebug('"nu" attribute missing for subscription: %s' % self['ri'])
			return (False, C.rcInsufficientArguments)

		# check other attributes
		self.normalizeURIAttribute('nfu')
		self.normalizeURIAttribute('nu')
		self.normalizeURIAttribute('su')		
		return (True, C.rcOK)
