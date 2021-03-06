from __future__ import print_function
from __future__ import division

"""
decoder.py

TODO: Trirgger should be a parameter or read from classifier
TODO: make use of get_decoder_info()


Kyuhwa Lee, 2014
Chair in Non-invasive Brain-machine Interface Lab (CNBI)
Swiss Federal Institute of Technology (EPFL)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

import pycnbi_config # from global common folder
import pycnbi_utils as pu
import time, os, sys, random, pdb
import q_common as qc
import numpy as np
import multiprocessing as mp
from multiprocessing import sharedctypes

def get_decoder_info(classifier):
	"""
	Get only the classifier information without connecting to a server

	Params
	------
		classifier: model file

	Returns
	-------
		info dictionary object
	"""

	model= qc.load_obj(classifier)
	if model == None:
		print('>> Error loading %s'% model)
		sys.exit(-1)

	cls= model['cls']
	psde= model['psde']
	labels= list(cls.classes_)
	w_seconds= model['w_seconds']
	w_frames= model['w_frames']
	wstep= model['wstep']
	sfreq= model['sfreq']
	psd_temp= psde.transform( np.zeros((1, len( model['picks'] ), w_frames)) )
	psd_shape= psd_temp.shape
	psd_size= psd_temp.size

	info= dict(labels=labels, cls=cls, psde=psde, w_seconds=w_seconds, w_frames=w_frames,\
		wstep=wstep, sfreq=sfreq, psd_shape=psd_shape, psd_size=psd_size)
	return info

class BCIDecoder:
	"""
	Decoder class
	"""
	def __init__(self, classifier=None, buffer_size=1.0, fake=False, amp_serial=None, amp_name=None):
		"""
		Params
		------
			classifier: classifier file
			spfilter: spatial filter to use
			buffer_size: length of the signal buffer in seconds
		"""

		from stream_receiver import StreamReceiver

		self.classifier= classifier
		self.buffer_sec= buffer_size
		self.fake= fake
		self.amp_serial= amp_serial
		self.amp_name= amp_name

		if self.fake==False:
			model= qc.load_obj(self.classifier)
			if model == None:
				self.print('Error loading %s'% model)
				sys.exit(-1)
			self.cls= model['cls']
			self.psde= model['psde']
			self.labels= list(self.cls.classes_)
			self.spfilter= model['spfilter']
			self.spchannels= model['spchannels']
			self.notch= model['notch']
			self.w_seconds= model['w_seconds']
			self.w_frames= model['w_frames']
			self.wstep= model['wstep']
			self.sfreq= model['sfreq']
			assert int(self.sfreq * self.w_seconds) == self.w_frames

			# window from StreamReceiver is 0-based
			self.picks= np.array( model['picks'] ) - 1

			# PSD buffer
			psd_temp= self.psde.transform( np.zeros((1, len( model['picks'] ), self.w_frames)) )
			self.psd_shape= psd_temp.shape
			self.psd_size= psd_temp.size
			self.psd_buffer= np.zeros((0, self.psd_shape[1], self.psd_shape[2] ))
			self.ts_buffer= []

			# Stream Receiver
			self.sr= StreamReceiver(window_size=self.w_seconds, amp_name=self.amp_name, amp_serial=self.amp_serial)
			if self.sfreq != self.sr.sample_rate:
				self.print('WARNING: The amplifier sampling rate (%.1f) != training data sampling rate (%.1f).'% (self.sr.sample_rate, self.sfreq))
		else:
			model= None
			self.psd_shape= None
			self.psd_size= None
			from triggerdef_16 import TriggerDef
			tdef= TriggerDef()
			# must be changed to non-specific labels
			self.labels= [tdef.by_key['DOWN_GO'], tdef.by_key['UP_GO']]

	def print(self, *args):
		if len(args) > 0: print('[BCIDecoder] ', end='')
		print(*args)

	def get_labels(self):
		"""
		Returns
		-------
			Class labels.
		"""
		return self.labels

	def start(self):
		pass

	def stop(self):
		pass

	def get_prob(self):
		"""
		Read the latest window

		Returns
		-------
			The likelihood P(X|C), where X=window, C=model
		"""
		tm= qc.Timer()
		if self.fake:
			probs= [ random.uniform(0.3, 0.8) ] # biased fake probs
			p_others= (1 - probs[0]) / ( len(self.labels) - 1 )
			for x in range(1, len(self.labels)):
				probs.append( p_others )
			time.sleep(0.0666) # simulated delay for PSD + RF on Rex laptop
		else:
			self.sr.acquire()
			w, ts= self.sr.get_window() # w = times x channels
			w= w.T # -> channels x times
			if self.spfilter=='car':
				if self.spchannels is None:
					raise RuntimeError, 'FUNCTION NOT IMPLEMENTED YET.'
				else:
					w[self.spchannels]= w[self.spchannels] - np.mean(w[self.spchannels], axis=0)
			w= w[self.picks] # assuming trigger channel

			# psd = channels x freqs
			psd= self.psde.transform( w.reshape( (1, w.shape[0], w.shape[1]) ) )

			# update psd buffer ( < 1 msec overhead )
			self.psd_buffer= np.concatenate( (self.psd_buffer, psd), axis=0 )
			self.ts_buffer.append(ts[0])
			if ts[0] - self.ts_buffer[0] > self.buffer_sec:
				# search speed comparison for ordered arrays:
				# http://stackoverflow.com/questions/16243955/numpy-first-occurence-of-value-greater-than-existing-value
				t_index= np.searchsorted(self.ts_buffer, ts[0]-1.0)
				self.ts_buffer= self.ts_buffer[t_index:]
				self.psd_buffer= self.psd_buffer[t_index:,:,:] # numpy delete is slower
			#assert ts[0] - self.ts_buffer[0] <= self.buffer_sec

			# make a feautre vector and classify
			feats= np.concatenate( psd[0] ).reshape(1, -1)
			probs= self.cls.predict_proba(feats)[0]

		return probs

	def get_prob_unread(self):
		return self.get_prob()

	def get_psd(self):
		"""
		Returns
		-------
			The latest computed PSD
		"""
		return self.psd_buffer[-1].reshape( (1,-1) )

class BCIDecoderDaemon:
	"""
	BCI Decoder daemon class

	Some codes are redundant because BCIDecoder class object cannot be pickled.
	BCIDecoder object must be created inside the child process.

	Constructor params:
		classifier: file name of the classifier
		buffer_size: buffer window size in seconds
		fake:
			False= Connect to an amplifier LSL server and decode
			True=  Create a mock decoder (fake probabilities biased to 1.0)
	"""

	def __init__(self, classifier=None, buffer_size=1.0, fake=False, amp_serial=None, amp_name=None):
		"""
		Params
		------
			classifier: classifier file.
			buffer_size: buffer size in seconds.
		"""

		self.classifier= classifier
		self.buffer_sec= buffer_size
		self.startmsg= 'Decoder daemon started.'
		self.stopmsg= 'Decoder daemon stopped.'
		self.fake= fake
		self.amp_serial= amp_serial
		self.amp_name= amp_name

		if fake==False:
			self.model= qc.load_obj(self.classifier)
			if self.model == None:
				self.print('Error loading %s'% self.model)
				sys.exit(-1)
			else:
				self.labels= self.model['cls'].classes_
		else:
			# create a fake decoder with LEFT/RIGHT classes
			self.model= None
			from triggerdef_16 import TriggerDef
			tdef= TriggerDef()
#			self.labels= [tdef.by_key['DOWN_GO'], tdef.by_key['UP_GO']]
			self.labels= [tdef.by_key['LEFT_GO'], tdef.by_key['RIGHT_GO']]   ## dongliu
			self.startmsg= 'FAKE ' + self.startmsg
			self.stopmsg= 'FAKE ' + self.stopmsg

		self.psdlock= mp.Lock()
		self.reset()
		self.start()

	def print(self, *args):
		if len(args) > 0: print('[BCIDecoderDaemon] ', end='')
		print(*args)

	def reset(self):
		"""
		Reset classifier to the initial state
		"""
		# share numpy array self.psd between processes.
		# to compute the shared memory size, we need to create a temporary decoder object.
		if self.fake==True:
			psd_size= None
			psd_shape= None
			psd_ctypes= None
			self.psd= None
		else:
			info= get_decoder_info(self.classifier)
			psd_size= info['psd_size']
			psd_shape= info['psd_shape'][1:] # we get only the last window
			psd_ctypes= mp.sharedctypes.RawArray('d', np.zeros(psd_size))
			self.psd= np.frombuffer(psd_ctypes, dtype=np.float64, count=psd_size)

		self.probs= mp.Array('d', [1.0/len(self.labels)]*len(self.labels))
		self.pread= mp.Value('i', 1)
		self.running= mp.Value('i', 0)
		self.return_psd= mp.Value('i', 0)
		mp.freeze_support()
		self.proc= mp.Process( target= self.daemon, args= \
			[self.classifier, self.probs, self.pread, self.running, self.return_psd, psd_ctypes, self.psdlock] )

	def daemon(self, classifier, probs, pread, running, return_psd, psd_ctypes, lock):
		"""
		The whole decoder loop runs on a child process because
		BCIDecoder object cannot be pickled.
		"""
		from numpy import ctypeslib

		decoder= BCIDecoder(classifier, buffer_size=self.buffer_sec,\
			fake=self.fake, amp_serial=self.amp_serial, amp_name= self.amp_name)
		if self.fake==False:
			psd= ctypeslib.as_array(psd_ctypes)
		else:
			psd= None

		while running.value == 1:
			probs[:]= decoder.get_prob()
			pread.value= 0

			if self.fake==False:
				# copy back PSD values only when needed
				# we don't need a lock (return_psd.value acts as a lock)
				if return_psd.value == 1:
					#lock.acquire()
					psd[:]= decoder.psd_buffer[-1].reshape( (1,-1) )
					#lock.release()
					return_psd.value= 0

	def start(self):
		"""
		Start the daemon
		"""
		if self.running.value==1:
			self.print('ERROR: Cannot start. Daemon already running. (PID %d)'% self.proc.pid)
			return
		self.running.value= 1
		self.proc.start()
		self.print(self.startmsg)

	def stop(self):
		"""
		Stop the daemon
		"""
		if self.running.value==0:
			self.print('Warning: Decoder already stopped.')
			return
		self.running.value= 0
		self.proc.join()
		self.reset()
		self.print(self.stopmsg)

	def get_labels(self):
		"""
		Returns
		-------
			Classifier labels.
		"""
		return self.labels

	def get_prob(self):
		"""
		Returns
		-------
			The last computed probability.
		"""
		self.pread.value= 1
		return self.probs[:]

	def get_prob_unread(self):
		"""
		Returns
		-------
			Probability if it's not read previously.
			None otherwise.
		"""
		if self.pread.value == 0:
			return self.get_prob()
		else:
			return None

	def get_psd(self):
		"""
		Returns
		-------
			The latest computed PSD
		"""
		self.return_psd.value= 1
		while self.return_psd.value==1:
			time.sleep(0.001)
		return self.psd


if __name__ == '__main__':
	from triggerdef_16 import TriggerDef
	#from triggerdef_antneuro_broken import TriggerDef

	#MODEL_FILE= r'D:\data\MI\rx1\2016\train\classifier\classifier-64bit.pcl'
#	MODEL_FILE= r'D:\data\MI\q5\2016\0413\fif\classifier\classifier-64bit.pcl'
	MODEL_FILE= r'E:\data\Records\fif\classifier\classifier-64bit.pcl'  # dongliu

	eeg_only= False

	import pylsl

	if len(sys.argv) == 2:
		amp_name= sys.argv[1]
		amp_serial= None
	elif len(sys.argv) == 3:
		amp_name, amp_serial= sys.argv[1:3]
	else:
		amp_name, amp_serial= pu.search_lsl(ignore_markers=True)
	if amp_name=='None':
		amp_name=None
	print('Connecting to a server %s (Serial %s).'% (amp_name, amp_serial) )


	# run on background
	decoder= BCIDecoderDaemon(MODEL_FILE, buffer_size=1.0, fake=False, amp_name=amp_name, amp_serial=amp_serial)

	# run on foreground (for debugging)
	#decoder= BCIDecoder(MODEL_FILE, buffer_size=1.0, amp_name=amp_name, amp_serial=amp_serial)

	# fake classifier
	#decoder= BCIDecoderDaemon(fake=True)


	# load trigger definitions for labeling
	tdef= TriggerDef()
	labels= [tdef.by_value[x] for x in decoder.get_labels()]

	probs=[0.5] * len(labels) # integrator
	tm= qc.Timer(autoreset=True)
	tm_cls= qc.Timer()

	while True:
		if isinstance(decoder, BCIDecoderDaemon):
			praw= decoder.get_prob_unread()
		else:
			praw= decoder.get_prob()

		if praw==None:
			if tm_cls.sec() > 5:
				print('[%.1fs] WARNING: No classification being done. Are you receiving data streams?'% pylsl.local_clock())
				tm_cls.reset()
			tm.sleep_atleast(0.001) # 1 ms
			continue

		print('[%8.1f msec]'% (tm_cls.sec()*1000.0), end='')
		for i in range(len(labels)):
			probs[i] = probs[i] * 0.8 + praw[i] * 0.2
			print('   %s %.3f (raw %.3f)'% (labels[i], probs[i], praw[i]), end='')
		maxi= qc.get_index_max( probs )
		print('   ', labels[maxi])

		tm_cls.reset()
