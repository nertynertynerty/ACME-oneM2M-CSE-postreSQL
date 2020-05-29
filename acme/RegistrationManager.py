#
#	RegistrationManager.py
#
#	(c) 2020 by Andreas Kraft
#	License: BSD 3-Clause License. See the LICENSE file for further details.
#
#	Managing resource / AE registrations
#

from Logging import Logging
from Constants import Constants as C
from Configuration import Configuration
import CSE, Utils
from resources import ACP


class RegistrationManager(object):

	def __init__(self):
		Logging.log('RegistrationManager initialized')


	def shutdown(self):
		Logging.log('RegistrationManager shut down')


	#########################################################################

	#
	#	Handle new resources in general
	#

	def checkResourceCreation(self, resource, originator, parentResource=None):
		if resource.ty == C.tAE:
			if (originator := self.handleAERegistration(resource, originator, parentResource)) is None:	# assigns new originator
				return (None, C.rcBadRequest)
		if resource.ty == C.tCSR:
			if not self.handleCSRRegistration(resource, originator):
				return (None, C.rcBadRequest)

		# Test and set creator attribute.
		if (rc := self.handleCreator(resource, originator)) != C.rcOK:
			return (None, rc)

		return (originator, C.rcOK)


	# Check for (wrongly) set creator attribute as well as assign it to allowed resources.
	def handleCreator(self, resource, originator):
		# Check whether cr is set. This is wrong
		if resource.cr is not None:
			Logging.logWarn('Setting "creator" attribute is not allowed.')
			return C.rcBadRequest
		# Set cr for some of the resource types
		if resource.ty in C.tCreatorAllowed:
			resource['cr'] = Configuration.get('cse.originator') if originator in ['C', 'S', '', None ] else originator
		return C.rcOK


	def checkResourceDeletion(self, resource, originator):
		if resource.ty == C.tAE:
			if not self.handleAEDeRegistration(resource):
				return (False, originator)
		if resource.ty == C.tCSR:
			if not self.handleCSRDeRegistration(resource):
				return (False, originator)
		return (True, originator)



	#########################################################################

	#
	#	Handle AE registration
	#

	def handleAERegistration(self, ae, originator, parentResource):

		# check for empty originator and assign something
		if originator is None or len(originator) == 0:
			originator = 'C'

		# Check for allowed orginator
		# TODO also allow when there is an ACP?
		if not Utils.isAllowedOriginator(originator, Configuration.get('cse.registration.allowedAEOriginators')):
			Logging.logDebug('Originator not allowed')
			return None


		# Assign originator for the AE
		if originator == 'C':
			originator = Utils.uniqueAEI('C')
		elif originator == 'S':
			originator = Utils.uniqueAEI('S')
		elif originator is not None:
			originator = Utils.getIdFromOriginator(originator)
		# elif originator is None or len(originator) == 0:
		# 	originator = Utils.uniqueAEI('S')
		Logging.logDebug('Registering AE. aei: %s ' % originator)

		ae['aei'] = originator					# set the aei to the originator
		ae['ri'] = Utils.getIdFromOriginator(originator, idOnly=True)		# set the ri of the ae to the aei (TS-0001, 10.2.2.2)

		# Verify that parent is the CSEBase, else this is an error
		if parentResource is None or parentResource.ty != C.tCSEBase:
			return None

		# Create an ACP for this AE-ID if there is none set
		if ae.acpi is None or len(ae.acpi) == 0:
			Logging.logDebug('Adding ACP for AE')
			cseOriginator = Configuration.get('cse.originator')

			# Add ACP for remote CSE to access the own CSE
			acpRes = self._createACP(parentResource=parentResource,
									 rn=C.acpPrefix + ae.rn,
									 createdByResource=ae.ri, 
								 	 originators=[ originator, cseOriginator ],
								 	 permission=Configuration.get('cse.acp.pv.acop'))
			if acpRes[0] is None:
				return False 
			ae['acpi'] = [ acpRes[0].ri ]		# Set ACPI (anew)

		return originator


	#
	#	Handle AE deregistration
	#

	def handleAEDeRegistration(self, resource):
		# remove the before created ACP, if it exist
		Logging.logDebug('DeRegisterung AE. aei: %s ' % resource.aei)
		Logging.logDebug('Removing ACP for AE')

		acpi = '%s/%s%s' % (Configuration.get('cse.rn'), C.acpPrefix, resource.rn)
		if self._removeACP(rn=acpi, resource=resource)[0] is None:
			return False
		return True



	#########################################################################

	#
	#	Handle CSR registration
	#

	def handleCSRRegistration(self, csr, originator):
		Logging.logDebug('Registering CSR. csi: %s ' % csr['csi'])

		# Create an ACP for this CSR if there is none set
		Logging.logDebug('Adding ACP for CSR')
		cseOriginator = Configuration.get('cse.originator')
		(localCSE, _) = Utils.getCSE()

		# Add ACP for remote CSE to access the own CSE
		acp = self._createACP(parentResource=localCSE,
							  rn='%s%s' % (C.acpPrefix, csr.rn),
						 	  createdByResource=csr.ri, 
							  originators=[ originator, cseOriginator ],
							  permission=C.permALL)
		if acp[0] is None:
			return False 
		csr['acpi'] = [ acp[0].ri ]	# Set ACPI (anew)

		# Add another ACP for remote CSE to access the CSE, at least to read
		cseAcp = self._createACP(parentResource=localCSE,
								 rn='%s%s_CSE' % (C.acpPrefix, csr.rn),
							 	 createdByResource=csr.ri, 
								 originators=[ originator, cseOriginator ],
								 permission=C.permRETRIEVE)
		if cseAcp[0] is None:
			return False

		# retrieve the CSEBase and assign the new ACP
		if (res := CSE.dispatcher.retrieveResource(localCSE.csi))[0] is not None:
			res[0].acpi.append(cseAcp[0].ri)
			CSE.dispatcher.updateResource(res[0], doUpdateCheck=False)

		return True


	#
	#	Handle CSR deregistration
	#

	def handleCSRDeRegistration(self, csr):
		Logging.logDebug('DeRegisterung CSR. csi: %s ' % csr['csi'])

		# remove the before created ACP, if it exist
		Logging.logDebug('Removing ACPs for CSR')
		(localCSE, _) = Utils.getCSE()

		# Retrieve CSR ACP
		acpi = '%s/%s%s' % (localCSE.rn, C.acpPrefix, csr.rn)
		if self._removeACP(rn=acpi, resource=csr)[0] is None:
			return False

		# Retrieve CSE ACP
		acpi = acpi + '_CSE'
		if (acpRes := self._removeACP(rn=acpi, resource=csr))[0] is None:
			return False

		#  Remove the reference from the CSE

		if acpRes[0].ri in localCSE.acpi:
			localCSE.acpi.remove(acpRes[0].ri)
		return CSE.dispatcher.updateResource(localCSE, doUpdateCheck=False)[0] is not None


	#########################################################################


	def _createACP(self, parentResource=None, rn=None, createdByResource=None, originators=None, permission=None):
		""" Create an ACP with some given defaults. """
		if parentResource is None or rn is None or originators is None or permission is None:
			return (None, C.BadRequest)
		cseOriginator = Configuration.get('cse.originator')
		selfPermission = Configuration.get('cse.acp.pvs.acop')
		origs = originators.copy()
		origs.append(cseOriginator)	# always append cse originator
		acp = ACP.ACP(pi=parentResource.ri, rn=rn, createdInternally=createdByResource)
		acp.addPermission(origs, permission)
		acp.addSelfPermission([ cseOriginator ], selfPermission)
		if not (res := self.checkResourceCreation(acp, cseOriginator, parentResource))[0]:
			return res
		return CSE.dispatcher.createResource(acp, parentResource=parentResource, originator=cseOriginator)


	def _removeACP(self, rn, resource):
		""" Remove an ACP created during registration before. """
		if (acpRes := CSE.dispatcher.retrieveResource(rn))[1] != C.rcOK:
			Logging.logWarn('Could not find ACP: %s' % rn)	# ACP not found, either not created or already deleted
		else:
			# only delete the ACP when it was created in the course of AE registration
			if  (ri := acpRes[0].createdInternally()) is not None and resource.ri == ri:
				return CSE.dispatcher.deleteResource(acpRes[0])
		return (None, C.rcBadRequest)

