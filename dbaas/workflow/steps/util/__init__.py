# -*- coding: utf-8 -*-
import logging
from util import exec_remote_command
from util import check_ssh
from util import get_credentials_for
from util import full_stack
from util import build_context_script
from time import sleep
from dbaas_cloudstack.models import HostAttr
from dbaas_cloudstack.provider import CloudStackProvider
from dbaas_credentials.models import CredentialType
from dbaas_dnsapi.provider import DNSAPIProvider
from workflow.exceptions.error_codes import DBAAS_0015

LOG = logging.getLogger(__name__)


def run_vm_script(workflow_dict, context_dict, script, reverse=False, wait=0):
    try:
        instances_detail = workflow_dict['instances_detail']

        final_context_dict = dict(
            context_dict.items() + workflow_dict['initial_context_dict'].items())

        if reverse:
            instances_detail_final = instances_detail[::-1]
        else:
            instances_detail_final = instances_detail

        for instance_detail in instances_detail_final:
            host = instance_detail['instance'].hostname
            host_csattr = HostAttr.objects.get(host=host)
            final_context_dict['IS_MASTER'] = instance_detail['is_master']
            command = build_context_script(final_context_dict, script)
            output = {}
            return_code = exec_remote_command(server=host.address,
                                              username=host_csattr.vm_user,
                                              password=host_csattr.vm_password,
                                              command=command,
                                              output=output)
            if return_code:
                raise Exception(
                    "Could not run script. Output: {}".format(output))

            sleep(wait)

        return True

    except Exception:
        traceback = full_stack()

        workflow_dict['exceptions']['error_codes'].append(DBAAS_0015)
        workflow_dict['exceptions']['traceback'].append(traceback)

        return False


def start_vm(workflow_dict):
    try:
        environment = workflow_dict['environment']
        cs_credentials = get_credentials_for(
            environment=environment, credential_type=CredentialType.CLOUDSTACK)
        cs_provider = CloudStackProvider(credentials=cs_credentials)
        instances_detail = workflow_dict['instances_detail']

        for instance_detail in instances_detail:
            instance = instance_detail['instance']
            host = instance.hostname
            host_csattr = HostAttr.objects.get(host=host)
            started = cs_provider.start_virtual_machine(
                vm_id=host_csattr.vm_id)
            if not started:
                raise Exception("Could not start host {}".format(host))

        for instance_detail in instances_detail:
            instance = instance_detail['instance']
            host = instance.hostname
            host_csattr = HostAttr.objects.get(host=host)
            host_ready = check_ssh(
                server=host.address, username=host_csattr.vm_user, password=host_csattr.vm_password, wait=5, interval=10)
            if not host_ready:
                error = "Host %s is not ready..." % host
                LOG.warn(error)
                raise Exception(error)

        from time import sleep
        sleep(60)

        return True
    except Exception:
        traceback = full_stack()

        workflow_dict['exceptions']['error_codes'].append(DBAAS_0015)
        workflow_dict['exceptions']['traceback'].append(traceback)

        return False


def stop_vm(workflow_dict):
    try:
        environment = workflow_dict['environment']
        cs_credentials = get_credentials_for(
            environment=environment, credential_type=CredentialType.CLOUDSTACK)
        cs_provider = CloudStackProvider(credentials=cs_credentials)
        instances_detail = workflow_dict['instances_detail']

        for instance_detail in instances_detail:
            instance = instance_detail['instance']
            host = instance.hostname
            host_csattr = HostAttr.objects.get(host=host)
            stoped = cs_provider.stop_virtual_machine(vm_id=host_csattr.vm_id)
            if not stoped:
                raise Exception("Could not stop host {}".format(host))

        return True

    except Exception:
        traceback = full_stack()

        workflow_dict['exceptions']['error_codes'].append(DBAAS_0015)
        workflow_dict['exceptions']['traceback'].append(traceback)

        return False


def test_bash_script_error():
    return """
      #!/bin/bash

      die_if_error()
      {
            local err=$?
            if [ "$err" != "0" ];
            then
                echo "$*"
                exit $err
            fi
      }"""


def build_mount_disk_script():
    return """
        echo ""; echo $(date "+%Y-%m-%d %T") "- Mounting data disk"
        echo "{{EXPORTPATH}}    /data nfs defaults,bg,intr,nolock 0 0" >> /etc/fstab
        die_if_error "Error setting fstab"
        mount /data
        die_if_error "Error setting fstab"
        """


def build_start_td_agent_script():
    return """
        echo ""; echo $(date "+%Y-%m-%d %T") "- Starting td_agent"
        /etc/init.d/td-agent start
        """


def switch_dns_forward(databaseinfra, source_object_list, ip_attribute_name,
                       dns_attribute_name, equivalent_atribute_name,
                       workflow_dict):

    for source_object in source_object_list:
        old_ip = source_object.__getattribute__(ip_attribute_name)
        dns = source_object.__getattribute__(dns_attribute_name)
        source_object.__setattr__(dns_attribute_name, old_ip)

        target_object = source_object.__getattribute__(
            equivalent_atribute_name)
        new_ip = target_object.__getattribute__(ip_attribute_name)
        target_object.__setattr__(dns_attribute_name, dns)

        LOG.info("Changing {}: from {} to {}".format(dns, old_ip, new_ip))

        DNSAPIProvider.update_database_dns_content(
            databaseinfra=databaseinfra,
            dns=dns,
            old_ip=old_ip,
            new_ip=new_ip)

        source_object.save()
        target_object.save()
        workflow_dict['objects_changed'].append({
            'source_object': source_object,
            'ip_attribute_name': ip_attribute_name,
            'dns_attribute_name': dns_attribute_name,
            'equivalent_atribute_name': equivalent_atribute_name,
        })


def switch_dns_backward(databaseinfra, source_object_list, ip_attribute_name,
                        dns_attribute_name, equivalent_atribute_name):

    for source_object in source_object_list:
        target_object = source_object.__getattribute__(
            equivalent_atribute_name)
        old_ip = target_object.__getattribute__(ip_attribute_name)
        dns = target_object.__getattribute__(dns_attribute_name)
        target_object.__setattr__(dns_attribute_name, old_ip)

        new_ip = source_object.__getattribute__(ip_attribute_name)
        source_object.__setattr__(dns_attribute_name, dns)

        LOG.info("Changing {}: from {} to {}".format(dns, old_ip, new_ip))

        DNSAPIProvider.update_database_dns_content(
            databaseinfra=databaseinfra,
            dns=dns,
            old_ip=old_ip,
            new_ip=new_ip)

        target_object.save()
        source_object.save()
