#
#	SecurityManager.py
#
#	(c) 2020 by Andreas Kraft
#	License: BSD 3-Clause License. See the LICENSE file for further details.
#
#	This entity handles access to resources
#


import ssl
from typing import List

from ..etc.Types import ResourceTypes as T, Permission, Result, CSERequest, ResponseCode as RC
from ..etc import Utils as Utils
from ..services import CSE as CSE
from ..services.Logging import Logging as L
from ..services.Configuration import Configuration
from ..resources.Resource import Resource
from ..resources.PCH_PCU import PCH_PCU
from ..helpers import TextTools


class SecurityManager(object):

	def __init__(self) -> None:
		self.enableACPChecks 			= Configuration.get('cse.security.enableACPChecks')
		self.fullAccessAdmin			= Configuration.get('cse.security.fullAccessAdmin')

		L.isInfo and L.log('SecurityManager initialized')
		if self.enableACPChecks:
			L.isInfo and L.log('ACP checking ENABLED')
		else:
			L.isInfo and L.log('ACP checking DISABLED')
		
		# TLS configurations (http)
		self.useTLSHttp 				= Configuration.get('http.security.useTLS')
		self.verifyCertificateHttp		= Configuration.get('http.security.verifyCertificate')
		self.tlsVersionHttp				= Configuration.get('http.security.tlsVersion').lower()
		self.caCertificateFileHttp		= Configuration.get('http.security.caCertificateFile')
		self.caPrivateKeyFileHttp		= Configuration.get('http.security.caPrivateKeyFile')

		# TLS and other configuration (mqtt)
		self.useTlsMqtt 				= Configuration.get('mqtt.security.useTLS')
		self.verifyCertificateMqtt		= Configuration.get('mqtt.security.verifyCertificate')
		self.caCertificateFileMqtt		= Configuration.get('mqtt.security.caCertificateFile')
		self.usernameMqtt				= Configuration.get('mqtt.security.username')
		self.passwordMqtt				= Configuration.get('mqtt.security.password')
		self.allowedCredentialIDsMqtt	= Configuration.get('mqtt.security.allowedCredentialIDs')
		


	def shutdown(self) -> bool:
		L.isInfo and L.log('SecurityManager shut down')
		return True


	def hasAccess(self, originator:str, resource:Resource, requestedPermission:Permission, checkSelf:bool=False, ty:int=None, isCreateRequest:bool=False, parentResource:Resource=None) -> bool:

		#  Do or ignore the check
		if not self.enableACPChecks:
			return True
		
		# grant full access to the CSE originator
		if originator == CSE.cseOriginator and self.fullAccessAdmin:
			L.isDebug and L.logDebug('Request from CSE Originator. OK.')
			return True
		

		if ty is not None:	# ty is an int

			# Checking for AE	
			if ty == T.AE and isCreateRequest:
				# originator may be None or empty or C or S. 
				# That is okay if type is AE and this is a create request
				if not originator or len(originator) == 0 or self.isAllowedOriginator(originator, CSE.registration.allowedAEOriginators):
					L.isDebug and L.logDebug('Originator for AE CREATE. OK.')
					return True

			# Checking for remoteCSE
			if ty == T.CSR and isCreateRequest:
				if self.isAllowedOriginator(originator, CSE.registration.allowedCSROriginators):
					L.isDebug and L.logDebug('Originator for CSR CREATE. OK.')
					return True
				else:
					L.isWarn and L.logWarn('Originator for CSR CREATE not found.')
					return False

			if T(ty).isAnnounced():
				if self.isAllowedOriginator(originator, CSE.registration.allowedCSROriginators) or originator[1:] == parentResource.ri:
					L.isDebug and L.logDebug('Originator for Announcement. OK.')
					return True
				else:
					L.isWarn and L.logWarn('Originator for Announcement not found.')
					return False
	
		# Allow some Originators to RETRIEVE the CSEBase
		if resource.ty == T.CSEBase and requestedPermission & Permission.RETRIEVE:

			# Allow registered AEs to RETRIEVE the CSEBase

			if CSE.storage.retrieveResource(aei=originator).resource:
				L.isDebug and L.logDebug(f'Allow registered AE Orignator {originator} to RETRIEVE CSEBase. OK.')
				return True
			
			# Allow remote CSE to RETRIEVE the CSEBase

			if originator == CSE.remote.registrarCSI:
				L.isDebug and L.logDebug(f'Allow registrar CSE Originnator {originator} to RETRIEVE CSEBase. OK.')
				return True
			if self.isAllowedOriginator(originator, CSE.registration.allowedCSROriginators):
				L.isDebug and L.logDebug(f'Allow remote CSE Orignator {originator} to RETRIEVE CSEBase. OK.')
				return True
			

		# Check parameters
		if not resource:
			L.isWarn and L.logWarn('Resource must not be None')
			return False
		if not requestedPermission or not (0 <= requestedPermission <= Permission.ALL):
			L.isWarn and L.logWarn('RequestedPermission must not be None, and between 0 and 63')
			return False

		L.isDebug and L.logDebug(f'Checking permission for originator: {originator}, ri: {resource.ri}, permission: {requestedPermission}, selfPrivileges: {checkSelf}')

		if resource.ty == T.GRP: # target is a group resource
			# Check membersAccessControlPolicyIDs if provided, otherwise accessControlPolicyIDs to be used
			
			if not (macp := resource.macp):
				L.isDebug and L.logDebug("MembersAccessControlPolicyIDs not provided, using AccessControlPolicyIDs")
				# FALLTHROUGH to the permission checks below
			
			else: # handle the permission checks here
				for a in macp:
					if not (acp := CSE.dispatcher.retrieveResource(a).resource):
						L.isDebug and L.logDebug(f'ACP resource not found: {a}')
						continue
					else:
						if acp.checkPermission(originator, requestedPermission, ty):
							L.isDebug and L.logDebug('Permission granted')
							return True
				L.isDebug and L.logDebug('Permission NOT granted')
				return False


		if resource.ty in [T.ACP, T.ACPAnnc]:	# target is an ACP or ACPAnnc resource
			if resource.checkSelfPermission(originator, requestedPermission):
				L.isDebug and L.logDebug('Permission granted')
				return True
			# fall-through

		else:		# target is any other resource type
			
			# If subscription, check whether originator has retrieve permissions on the subscribed-to resource (parent)	
			if ty == T.SUB and parentResource:
				if self.hasAccess(originator, parentResource, Permission.RETRIEVE) == False:
					return False


			# When no acpi is configured for the resource
			if not (acpi := resource.acpi):
				L.isDebug and L.logDebug('Handle with missing acpi in resource')

				# if the resource *may* have an acpi
				if resource._attributes and 'acpi' in resource._attributes:

					# Check holder attribute
					if holder := resource.hld:
						if holder == originator:	# resource.holder == originator -> all access
							L.isDebug and L.logDebug('Allow access for holder')
							return True
						# When holder is set, but doesn't match the originator then fall-through to fail
						
					# Check resource creator
					elif (creator := resource.getOriginator()) and creator == originator:
						L.isDebug and L.logDebug('Allow access for creator')
						return True
					
					# Fall-through to fail

				# resource doesn't support acpi attribute
				else:
					if resource.inheritACP:
						L.isDebug and L.logDebug('Checking parent\'s permission')
						parentResource = CSE.dispatcher.retrieveResource(resource.pi).resource
						return self.hasAccess(originator, parentResource, requestedPermission, checkSelf, ty, isCreateRequest)

				L.isDebug and L.logDebug('Permission NOT granted for resource w/o acpi')
				return False

			for a in acpi:
				if not (acp := CSE.dispatcher.retrieveResource(a).resource):
					L.isDebug and L.logDebug(f'ACP resource not found: {a}')
					continue
				if checkSelf:	# forced check for self permissions
					if acp.checkSelfPermission(originator, requestedPermission):
						L.isDebug and L.logDebug('Permission granted')
						return True				
				else:
					# L.isWarn and L.logWarn(acp)
					if acp.checkPermission(originator, requestedPermission, ty):
						L.isDebug and L.logDebug('Permission granted')
						return True

		# no fitting permission identified
		L.isDebug and L.logDebug('Permission NOT granted')
		return False


	def hasAcpiUpdatePermission(self, request:CSERequest, targetResource:Resource, originator:str) -> Result:
		"""	Check whether this is actually a correct update of the acpi attribute, and whether this is actually allowed.
		"""
		updatedAttributes = Utils.findXPath(request.dict, '{0}')

		# Check that acpi, if present, is the only attribute
		if 'acpi' in updatedAttributes:
			if len(updatedAttributes) > 1:
				L.logDebug(dbg := '"acpi" must be the only attribute in update')
				return Result(status=False, rsc=RC.badRequest, dbg=dbg)
			
			# Check whether the originator has UPDATE privileges for the acpi attribute (pvs!)
			if not targetResource.acpi:
				if originator != targetResource.getOriginator():
					L.isDebug and L.logDebug(dbg := f'No access to update acpi for originator: {originator}')
					return Result(status=False, rsc=RC.originatorHasNoPrivilege, dbg=dbg)
				else:
					pass	# allowed for creating originator
			else:
				# test the current acpi whether the originator is allowed to update the acpi
				for ri in targetResource.acpi:
					if not (acp := CSE.dispatcher.retrieveResource(ri).resource):
						L.isWarn and L.logWarn(f'Access Check for acpi: referenced <ACP> resource not found: {ri}')
						continue
					if acp.checkSelfPermission(originator, Permission.UPDATE):
						break
				else:
					L.isDebug and L.logDebug(dbg := f'Originator: {originator} has no permission to update acpi for: {targetResource.ri}')
					return Result(status=False, rsc=RC.originatorHasNoPrivilege, dbg=dbg)

			return Result(status=True, data=True)	# hack: data=True indicates that this is an ACPI update after all

		return Result(status=True)


	def isAllowedOriginator(self, originator:str, allowedOriginators:List[str]) -> bool:
		""" Check whether an Originator is in the provided list of allowed 
			originators. This list may contain regex.
		"""
		# if L.isDebug: L.logDebug(f'Originator: {originator}')
		# if L.isDebug: L.logDebug(f'Allowed originators: {allowedOriginators}')

		if not originator or not allowedOriginators:
			return False
		for ao in allowedOriginators:
			if TextTools.simpleMatch(Utils.getIdFromOriginator(originator), ao):
				return True
		return False


	def hasAccessToPCU(self, originator:str, resource:PCH_PCU) -> bool:
		"""	Check whether the originator has access to the PCU resource.
			This should be done to check the parent PCH, but the originator
			would be the same as the PCU, so we can optimize this a bit.
		"""
		return originator == resource.getOriginator()



	##########################################################################
	#
	#	Certificate handling
	#

	def getSSLContext(self) -> ssl.SSLContext:
		"""	Depending on the configuration whether to use TLS, this method creates a new `SSLContext`
			from the configured certificates and returns it. If TLS is disabled then `None` is returned.
		"""
		context = None
		if self.useTLSHttp:
			L.isDebug and L.logDebug(f'Setup SSL context. Certfile: {self.caCertificateFileHttp}, KeyFile:{self.caPrivateKeyFileHttp}, TLS version: {self.tlsVersionHttp}')
			context = ssl.SSLContext(
							{ 	'tls1.1' : ssl.PROTOCOL_TLSv1_1,
								'tls1.2' : ssl.PROTOCOL_TLSv1_2,
								'auto'   : ssl.PROTOCOL_TLS,			# since Python 3.6. Automatically choose the highest protocol version between client & server
							}[self.tlsVersionHttp.lower()]
						)
			context.load_cert_chain(self.caCertificateFileHttp, self.caPrivateKeyFileHttp)
		return context


	# def getSSLContextMqtt(self) -> ssl.SSLContext:
	# 	"""	Depending on the configuration whether to use TLS for MQTT, this method creates a new `SSLContext`
	# 		from the configured certificates and returns it. If TLS for MQTT is disabled then `None` is returned.
	# 	"""
	# 	context = None
	# 	if self.useMqttTLS:
	# 		L.isDebug and L.logDebug(f'Setup SSL context for MQTT. Certfile: {self.caCertificateFile}, KeyFile:{self.caPrivateKeyFile}, TLS version: {self.tlsVersion}')
	# 		context = ssl.SSLContext(
	# 						{ 	'tls1.1' : ssl.PROTOCOL_TLSv1_1,
	# 							'tls1.2' : ssl.PROTOCOL_TLSv1_2,
	# 							'auto'   : ssl.PROTOCOL_TLS,			# since Python 3.6. Automatically choose the highest protocol version between client & server
	# 						}[self.tlsVersionMqtt.lower()]
	# 					)
	# 		if self.caCertificateFileMqtt:
	# 			#context.load_cert_chain(self.caCertificateFileMqtt, self.caPrivateKeyFileMqtt)
	# 			#print(self.caCertificateFileMqtt)
	# 			context.load_verify_locations(cafile=self.caCertificateFileMqtt)
	# 			#context.load_cert_chain(certfile=self.caCertificateFileMqtt)
	# 		context.verify_mode = ssl.CERT_REQUIRED if self.verifyCertificateMqtt else ssl.CERT_NONE
	# 	return context
