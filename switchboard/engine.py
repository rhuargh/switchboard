
import sys
import time
import json
import importlib
import requests

from threading import Lock

from switchboard.device import RESTDevice
from switchboard.module import SwitchboardModule


class SwitchboardEngine:
    def __init__(self, config):
        # Determines if the SwitchboardEngine logic is running or not
        self.running = False

        # Set to true if SwitchboardEngine should terminate
        self.terminate = False

        # The switchboard config object
        self.config = config

        # Map of host URL -> _Host object
        self.hosts = {}

        # Map of module name -> _Module object
        self.modules = {}

        # Map of all the Switchboard devices (name -> device instance)
        self.devices = {}

        # Lock used to synchronise switchboard with its settings
        self.lock = Lock()


    def init_config(self):
        ''' Initialise the switchboard hosts and modules according to
            the config file '''

        print("Initialising switchboard config...")

        for host_url in self.config.get('hosts'):
            try:
                self.upsert_host(host_url)
            except Exception as e:
                sys.exit('Error adding host {}: {}'.format(host_url, e))


    def upsert_host(self, host_url):
        ''' Insert or update a Switchboard host. This method throws
            an exception if any issues are encountered and complies to
            the strong exception guarantee (i.e., if an error is raised
            SwitchboardEngine will keep running without changing state) '''

        if not host_url.startswith('http://'):
            host_url = 'http://' + host_url

        if host_url in self.hosts:
            print('Updating host {}'.format(host_url))
        else:
            print('Adding host {}'.format(host_url))

        # Get the info of all the devices
        info_url = host_url + '/devices_info'
        host_devices = requests.get(info_url).json()['devices']

        # TODO check formatting for host_url + '/devices_value'

        print('Adding devices:')

        new_devices = {}

        for device in host_devices:
            name = device['name']

            # Check we don't have duplicate devices on this host
            if name in new_devices:
                raise Exception('Device "{}" exists twice on host {}'.format(name, host_url))

            # Make sure we don't add a device that already exists on a
            # different host
            if name in self.devices and self.devices[name].host_url != host_url:
                clashing_host = self.devices[name].host_url
                msg = 'Device "{}" already exists for host {}'.format(name, clashing_host)
                raise Exception(msg)

            new_devices[name] = RESTDevice(device, host_url, self.set_remote_device_value)
            print('\t{}'.format(name))

        # In case we are updating a host we need to delete all its
        # known 'old' devices and remove it from the input hosts set
        if host_url in self.hosts:
            for old_device in self.hosts[host_url].devices:
                del self.devices[old_device]

        # TODO make sure that any deleted devices aren't used by modules

        # And now add all the 'new' host information
        self.devices.update(new_devices)
        self.hosts[host_url] = _Host(host_url, new_devices.keys())

        # Load the initial values
        self._update_devices_values()


    def upsert_switchboard_module(self, module_name):
        module_func_name = module_name.split('.')[-1]
        pymodule = '.'.join(module_name.split('.')[:-1])

        if pymodule in sys.modules:
            pymodule_instance = importlib.reload(sys.modules[pymodule])
        else:
            pymodule_instance = importlib.import_module(pymodule)

        # Instantiate the module and update data structures
        swbmodule = getattr(pymodule_instance, module_func_name)
        swbmodule.module_class.enabled = True
        self.modules[module_name] = swbmodule

        # Make sure all the inputs and outputs line up correctly
        swbmodule.module_class.create_argument_list(self.devices)


    def enable_switchboard_module(self, module_name):
        if not module_name in modules:
            raise Exception('Unknown module {}'.format(module_name))

        module_class = modules[module_name].module_class

        if module_class.error:
            print('Module {} enabled but will not run due to error: {}'.format(
                module_name, module_class.error))

        module_class.enabled = True


    def disable_switchboard_module(self, module_name):
        if not module_name in modules:
            raise Exception('Unknown module {}'.format(module_name))

        modules[module_name].module_class.enabled = False


    def run(self):
        while not self.terminate:
            try:
                time.sleep(float(self.config.get('poll_period')))
                if self.running:
                    with self.lock:
                        self._update_devices_values()
                        self._check_modules()
            except KeyboardInterrupt:
                break


    def set_remote_device_value(self, device, value):
        payload = json.dumps({'name': device.name, 'value': str(value)})
        r = requests.put(device.host_url + '/device_set', data=payload)
        try:
            response = r.json()
            if 'error' in response:
                print('Error: ' + response['error'])
        except Exception as e:
            print('Exception "{}": {}'.format(e, r.content))


    def _check_modules(self):
        for module in self.modules.values():
            module()


    def _update_devices_values(self):
        ''' Get updated values from all the input devices '''

        for host in self.hosts.values():
            values_url = host.url + '/devices_value'

            try:
                values = requests.get(values_url)
                host.connected = True
            except:
                host.connected = False
                host.on_error('Unable to access host {}'.format(host.url))
                continue

            try:
                values_json = values.json()
            except:
                host.on_error('Invalid json formatting for host {}'.format(url))
                continue

            error = self._check_values_json_formatting(host.url, values_json)
            if error:
                host.on_error(error)
            else:
                host.on_no_error()
                for device_json in values_json['devices']:
                    self._update_device_value(device_json)


    def _check_values_json_formatting(self, url, values_json):
        ''' Check that the request body is correctly formatted '''

        if 'error' in values_json:
            return 'Error for host {}: {}'.format(url, values_json['error'])

        if not 'devices' in values_json:
            return 'Error for host {}: no "devices" field'.format(url)

        for device_json in values_json['devices']:
            if not 'name' in device_json:
                return 'Error for host {}: found device with no name'.format(url)

            if not 'value' in device_json and not 'error' in device_json:
                return 'Error for host {}: device {} has no value or error field'.format(
                        url, device_json['name'])


    def _update_device_value(self, device_json):
        ''' Given a correctly formatted json encoded device value,
            update the local device object '''

        device = self.devices[device_json['name']]

        if 'error' in device_json:
            if not device.error:
                print('Device {} has reported an error: {}'.format(
                    device_json['name'], device_json['error']))
            device.error = device_json['error']

        elif 'value' in device_json:
            if device.error:
                print('Device {} no longer reporting error'.format(
                    device_json['name']))
                device.error = None
            device.update_value(device_json['value'])



class _Host:
    def __init__(self, url, devices):
        self.url = url
        self.connected = False
        self.error = None
        self.devices = set(devices)


    def on_error(self, msg):
        if not self.error:
            print('Encountered error for host {}: {}'.format(self.url, msg))
            self.error = msg

            for device in self.devices:
                device.error = "Host error"


    def on_no_error(self):
        if self.error:
            print('Host {} no longer in error state'.format(self.url))
            self.error = None

            for device in self.devices:
                device.error = None