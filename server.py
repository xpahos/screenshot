#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

import redis
import pickle
import getopt
import time
import logging
import os
import sys
import pwd
import subprocess
import re
import urllib2
import signal
import multiprocessing
import httplib
import resource

# Define regexps

xvfb_reg = re.compile(r'Xvfb :(\d+)')
browser_reg = re.compile(r'0x(\d+) .* \("opera" "Opera"\)  1024x768') 

# Classes

class Services:
    """
        Class controlling main thread
    """
    log_file = '/var/log/screenshot/server.log'
    pid_file = '/var/run/screenshot.pid'
    user = None
    
    # Working directory and uid for user
    u_uid = None
    u_home = None
    
    def __init__(self):
        """
            Init logger and some variables from user
        """
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'l:p:u:h', ['log', 'pid', 'user', 'help'])
        except getopt.GetoptError:
            self.help()
            sys.exit(2)
        
        for opt, arg in opts:
            if opt in ('-h', '--help'):
                self.help()
                sys.exit() 
            elif opt in ('-l', '--log'):
                self.log_file = arg
            elif opt in ('-p', '--pid'):
                self.pid_file = arg
            elif opt in ('-u', '--user'):
                self.user = arg
        
        if self.user:
            if not os.geteuid() == 0:
                sys.exit('You need root privileges to set user')
            try:
                userl = pwd.getpwnam(self.user)
                self.u_uid = userl.pw_uid
                self.u_home = userl.pw_dir
            except KeyError:
                sys.exit('User {0} does not exist'.format(self.user))
            
            os.setuid(self.u_uid)
            os.chdir(self.u_home)
        else:
            sys.exit('You must set user')
            
            
    def help(self):
        print """
    Usage: {0} --u screenshot -l /var/log/screenshot/server.log -p /var/run/screenshot.pid
    
        --user   Set unprivileged user for process. This user can't be nobody, because script
        -u       reads home directory from passwd and uses it for Chrome user data dirs.
    
       --log     Set log file.
       -l
    
       --pid     Set pid file.
       -p
    
       --help    This help.
       -h
        """.format(sys.argv[0])
        
    def create_daemon(self):
        """
            Fork process for detaching from console.
        """
        try:
            pid = os.fork()
        except OSError:
            sys.exit('Can not demonize process')
        
        if pid == 0:
            os.setsid()
            
            try:
                pid = os.fork()
            except OSError:
                sys.exit('Can not demonize process')
            
            if pid == 0:
                os.chdir(self.u_home)
                os.umask(0)
            else:
                os._exit(0)
        else:
            os._exit(0)
        
        maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
        if (maxfd == resource.RLIM_INFINITY):
            maxfd = 1024 
        for fd in range(0, maxfd):
            try:
                os.close(fd)
            except OSError:
                pass
        
        if hasattr(os, 'devnull'):
            console = os.devnull
        else:
            console = '/dev/null'
        os.open(console, os.O_RDWR)
        
        os.dup2(0, 1)
        os.dup2(0, 2)
        
        return (0)
    
class Workers:
    displays = []
    locked_displays = []
    
    connection = None
    
    running = True
    
    def __init__(self, logger):
        #
        # Get working displays and start subprocesses
        self.list_display() 
        logger.info('Found displays: {0}'.format(' '.join(self.displays)))
        
        self.connection = redis.Redis('localhost')
        
    def sig_handler(self, signum, frame):
        """
            Set termination flag
        """
        self.running = False 
        return
        
    def list_display(self):
        """
            Get list of working virtual framebuffers
        """
        proc = subprocess.Popen(['/bin/ps', 'ax'], stdout=subprocess.PIPE)
        self.displays = xvfb_reg.findall(proc.communicate()[0])
        
    
    def get_display(self, lock):
        """
            Get display for opera instance.
        """
        while True:
            lock.acquire()
            free = list(set(self.displays).difference(self.locked_displays))
            if len(free):
                self.locked_displays.append(free[0])
                lock.release()
                return free[0]
            
            lock.release()
            time.sleep(3)
                
        

    def check_url_code(self, url):
        """
            Try fetch url before processing.
            Return True if returned request code is 200 OK else False
        """
        try:
            url = urllib2.urlopen(url)
            code = url.getcode()
    
            if code == 200:
                return True
            else:
                return False
        except:
        #except (urllib2.URLError, httplib.InvalidURL, httplib.BadStatusLine, ValueError):
            return False
        
    def get_screenshot(self, data, display):
        """
            Fork background opera process and then search window with url.
            Wait for 30 seconds and take screenshot of the window.
            xkill killing opera window, cuz without opened tabs opera will be terminated.
        """
        
        try:
            os.remove('.opera/{0}/sessions/autosave.win'.format(display))
        except:
            pass
        proc = subprocess.Popen(['/usr/bin/opera', '-geometry', '1024x768+0+0', '-fullscreen', '-display', ':{0}'.format(display), '-pd', '.opera/{0}'.format(display), data['url']])
        time.sleep(10)
        
        if int(data['size']) == 120:
            geometry = '120x90'
        elif int(data['size']) == 240:
            geometry = '240x151'
        elif int(data['size']) == 400:
            geometry = '400x300'
    
        try:
            os.makedirs(data['path'])
        except OSError:
            pass
        
        
        xwin_proc = subprocess.Popen(['/usr/bin/xwininfo', '-display', ':{0}'.format(display), '-root', '-tree'], stdout=subprocess.PIPE)
        xwin_info = xwin_proc.communicate()[0]
        window = browser_reg.findall(xwin_info)[0]
        
        time.sleep(5)
        
        pimport = subprocess.Popen(['/usr/bin/import', '-display', ':{0}'.format(display), '-window', 'root', '-resize', geometry, data['file']])
        pimport.wait()
        
        pxkill = subprocess.Popen(['/usr/bin/xkill', '-display', ':{0}'.format(display), '-id', '0x{0}'.format(window)])
        pxkill.wait()
        
        proc.wait()
        
        try:
            if xwin_proc.poll() != 0:
                xwin_proc.kill()
                
            if pimport.poll() != 0:
                pimport.kill()
                
            if pxkill.poll() != 0:
                pxkill.kill()
            
            if proc.poll() != 0:
                proc.kill()
        except OSError:
            pass
        
        
        return { 'display' : display, 'window' : window, 'geometry' : geometry, 'data': data, 'pid' : str(os.getpid()) }
        
    def main(self, job, lock, logger):
        """
            Checking for file has been created early in another queue, url and url locks
        """
        data = pickle.loads(job)
        
        if os.path.isfile(data['path']):
            self.connection.hdel('jobs', data['md5_url'])
            self.connection.hincrby('stats', 'completed', 1)
        elif not self.check_url_code(data['url']): 
            logger.error('Error fetching {0}'.format(data['url']))
            self.connection.hincrby('stats', 'completed', 1)
        else:
            return self.get_display(lock)
        
        return None
        
def wrapper_callback(data, lock, logger):
    lock.acquire() 
    workers.locked_displays.remove(data['display'])
    lock.release()
    
    logger.info('Screenshot {geometry} for {url}: display={display}, pid={pid}, window=0x{window}, file={file}'.format(
                                                                                                            geometry = data['geometry'], 
                                                                                                            url = data['data']['url'], 
                                                                                                            display = data['display'], 
                                                                                                            pid = data['pid'],
                                                                                                            window = data['window'], 
                                                                                                            file = data['data']['file']))
    
    workers.connection.hdel('jobs', data['data']['md5_url'])
    workers.connection.hincrby('stats', 'completed', 1)
    
    return

def wrapper_worker(job, display):
    data = pickle.loads(job)
        
    return workers.get_screenshot(data, display)

if __name__ == '__main__':
    services = Services()
    
    # Fork child process for demonization
    services.create_daemon()
    
    # Open logfile
    logging.basicConfig(level=logging.INFO,
                format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                datefmt='%m-%d %H:%M',
                filename=services.log_file)
    logger = logging.getLogger(name='screenshot')
    
    # Write pid to pidfile 
    pid = os.getpid()
    open(services.pid_file, 'w').write(str(pid))
    logger.info('Starting server with pid {0}'.format(str(pid)))
    
    workers = Workers(logger)
    
    # Handle termination signals
    signal.signal(signal.SIGTERM, workers.sig_handler)
    
    pool = multiprocessing.Pool(processes=len(workers.displays))
    lock = multiprocessing.Manager().Lock()
     
    while workers.running:
        job = workers.connection.lpop('high_priority')    
        if job is None:
            job = workers.connection.rpop('low_priority')
        if not job is None:
            display = workers.main(job, lock, logger)
            if display:
                pool.apply_async(wrapper_worker, (job, display), callback = lambda data: wrapper_callback(data, lock, logger) )
        else:
            time.sleep(5)
    
    logger.info('Server stopped') 

    pool.close()
    pool.join()
    sys.exit()

