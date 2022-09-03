import sys
import os
import re
from kubernetes import client, config


config.load_kube_config()
client_v1 = client.CoreV1Api()
api = client.AppsV1Api()
avoided_namespaces = ['kube-system', 'kube-node-lease', 'kube-public', 'ingress-nginx']


def get_namespaces() -> list:
    namespaces_list = [ns.metadata.name for ns in client_v1.list_namespace().items
                       if ns.metadata.name not in avoided_namespaces]
    return namespaces_list


def get_pods_by_ns() -> list:
    pods = [pod.metadata.name for pod in client_v1.list_namespaced_pod(namespace).items]
    return pods


def get_crash_pods_by_ns() -> list:
    crash_pods_list = [[pod.metadata.name, pod.metadata.labels['app']]
                       for pod in client_v1.list_namespaced_pod(namespace).items
                       if not pod.status.container_statuses[0].ready
                       and not pod.status.container_statuses[0].state.waiting is None
                       if pod.status.container_statuses[0].state.waiting.reason == 'CrashLoopBackOff']
    return crash_pods_list


def get_deployment_by_ns() -> list:
    deploy_list = [[deploy.metadata.labels['app'], deploy.status.unavailable_replicas]
                   for deploy in api.list_namespaced_deployment(namespace).items]
    return deploy_list


def scale_deployment(deployment: str, replicas: int):
    print(f'Scaling down {deployment}...')
    api.patch_namespaced_deployment_scale(deployment, namespace, {'spec': {'replicas': replicas}})


def get_write_logs(pod_name: str):
    folder = "crash_logs"
    parent_dir = os.getcwd()
    path = os.path.join(parent_dir, folder)

    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        print(f"Directory {folder} can not be created")

    log = client_v1.read_namespaced_pod_log(pod_name, namespace)
    with open(f'{path}/{pod_name}.log', 'w', encoding='utf-8') as f:
        f.write(log)


def get_pods_matches(podslist):
    added_text = '-app'
    pods = [re.sub("-app$", "", pod[1]) if added_text in pod[1] else pod[1] for pod in podslist]
    matches = dict((i, pods.count(i)) for i in pods if pods.count(i) > 1)
    pods_matches = [[key, value] for key, value in matches.items()]

    return pods_matches


def validate_deployments(podmatches, deploylist):
    print('Validating...')
    [[scale_deployment(deploy[0], 0)
      for deploy in deploylist if pod[0] == deploy[0] and pod[1] == deploy[1]]
     for pod in podmatches]


def help_usage():
    print("""
        Usage: python3 crash_cleaner.py NAMESPACE [--get-logs]
        Args:
            NAMESPACE: 	set a namespace to execute Script
            --get-logs:	to get logs from pods in CrashLoopBackOff status
        """)
    exit(0)


def run():
    crash_pods = get_crash_pods_by_ns()
    if not crash_pods:
        print(f'There are not pods in CrashLoopBackOff status')
        exit(0)
    if len(sys.argv) == 3 and sys.argv[2] == '--get-logs':
        print('Getting logs...')
        [get_write_logs(pod[0]) for pod in crash_pods]

    print(f'The following pods ({len(crash_pods)}) are in status CrashLoopBackOff: ')
    [print(pod[0]) for pod in crash_pods]
    get_pods_matches(crash_pods)
    # validate_deployments(get_pods_matches(crash_pods), get_deployment_by_ns())


def test():
    pass


if __name__ == '__main__':
    try:
        if len(sys.argv) == 2 and sys.argv[1] == 'help':
            help_usage()
        if len(sys.argv) == 1:
            raise ValueError()
        namespace = sys.argv[1]
        if namespace in get_namespaces():
            run()
        else:
            print(f'The namespace does not exist in the cluster or is forbidden')

    except ValueError:
        print(f'You must provide one of these namespaces: \n')
        print(*get_namespaces())
        exit(128)
