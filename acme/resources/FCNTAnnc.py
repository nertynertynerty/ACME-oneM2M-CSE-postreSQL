#
#	FCNTAnnc.py
#
#	(c) 2020 by Andreas Kraft
#	License: BSD 3-Clause License. See the LICENSE file for further details.
#
#	FCNT : Announceable variant
#


from ..etc.Types import AttributePolicyDict, ResourceTypes as T, JSON
from ..resources.AnnouncedResource import AnnouncedResource
from ..resources.Resource import *


class FCNTAnnc(AnnouncedResource):

	# Specify the allowed child-resource types
	_allowedChildResourceTypes = [	T.ACTR, T.ACTRAnnc, T.CNT, T.CNTAnnc, T.CIN, T.CINAnnc, 
									T.FCNT, T.FCNTAnnc, T.FCI, T.TS, T.TSAnnc, T.SUB ]

	# Attributes and Attribute policies for this Resource Class
	# Assigned during startup in the Importer
	_attributes:AttributePolicyDict = {		
		# Common and universal attributes for announced resources
		'rn': None,
		'ty': None,
		'ri': None,
		'pi': None,
		'ct': None,
		'lt': None,
		'et': None,
		'lbl': None,
		'acpi':None,
		'daci': None,
		'ast': None,
		'loc': None,
		'lnk': None,

		# Resource attributes
		'cnd': None,
		'or': None,
		'nl': None,
		'mni': None,
		'mia': None,
		'mbs': None
	}


	def __init__(self, dct:JSON = None, pi:str = None, create:bool = False) -> None:
		super().__init__(T.FCNTAnnc, dct, pi = pi, create = create)

