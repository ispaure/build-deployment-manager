"""Disposable upstream CPython testbed setup, independent of project acceptance."""
import importlib.util
from pathlib import Path
import plistlib
import re
import shutil
import sys

from commonUtils.runtime.streams import file_sha256


def scene_source(scene_class, *, comment='CPython testbed scene compatibility.'):
    return '''
// COMMENT_TOKEN
@interface SCENE_CLASS_TOKEN : UIResponder <UIWindowSceneDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation SCENE_CLASS_TOKEN
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session
      options:(UISceneConnectionOptions *)connectionOptions {
    if (![scene isKindOfClass:[UIWindowScene class]]) { return; }
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.window.rootViewController = [[UIViewController alloc] init];
    [self.window makeKeyAndVisible];
}
@end
'''.replace('SCENE_CLASS_TOKEN', scene_class).replace('COMMENT_TOKEN', comment)


def digest(path):
    return file_sha256(path)


def modernize(testbed, *, scene_class, scene_source, deployment_target, adapter_sha256):
    """Preserve upstream XCTest/Python setup; add the app's required UI scene."""
    app = Path(testbed) / 'iOSTestbed'
    delegate, info = app / 'AppDelegate.m', app / 'iOSTestbed-Info.plist'
    text = delegate.read_text()
    data = plistlib.loads(info.read_bytes())
    configuration = {'UIWindowSceneSessionRoleApplication': [{
        'UISceneConfigurationName': 'Core runtime tests',
        'UISceneClassName': 'UIWindowScene', 'UISceneDelegateClassName': scene_class}]}
    manifest = data.get('UIApplicationSceneManifest', {})
    existing = manifest.get('UISceneConfigurations', {})
    if existing and existing != configuration:
        raise ValueError('Unexpected upstream scene configuration; inspect before adapting.')
    if '@implementation AppDelegate' not in text:
        raise ValueError('Unexpected upstream testbed app delegate.')
    project = Path(testbed) / 'iOSTestbed.xcodeproj/project.pbxproj'
    project_text = project.read_text()
    target = re.compile(r'(IPHONEOS_DEPLOYMENT_TARGET = )(\d+(?:\.\d+)?)(;)')
    if not target.search(project_text):
        raise ValueError('Missing upstream deployment target; inspect before adapting.')
    project_text = target.sub(lambda match: match[1] + (deployment_target if tuple(map(int, match[2].split("."))) < tuple(map(int, deployment_target.split("."))) else match[2]) + match[3], project_text)
    before = {'delegate': digest(delegate), 'info': digest(info), 'project': digest(project)}
    if scene_class not in text:
        delegate.write_text(text + scene_source)
    elif not text.endswith(scene_source):
        raise ValueError('Testbed scene adapter differs from the reviewed source.')
    data['UIApplicationSceneManifest'] = dict(manifest, UIApplicationSupportsMultipleScenes=False,
                                            UISceneConfigurations=configuration)
    info.write_bytes(plistlib.dumps(data))
    project.write_text(project_text)
    return dict(before=before, after={'delegate': digest(delegate), 'info': digest(info), 'project': digest(project)},
                adapter_sha256=adapter_sha256, manager_adapter_sha256=digest(__file__),
                deployment_target=deployment_target)


def normalize_log(raw, output):
    """Strip only the upstream test app's system-log prefix, in either timezone."""
    prefix = re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d+:\d{2}:\d{2}\.\d+[+-]\d{4}\s+iOSTestbed\[\d+:\w+\] ')
    text = Path(raw).read_text(encoding='utf-8', errors='backslashreplace')
    Path(output).write_text(''.join(prefix.sub('', line) for line in text.splitlines(keepends=True)), encoding='utf-8')


def prepare_ios(cache, testbed, framework, payload, test_args, *, command, adapt):
    """Clone upstream testbed and configure caller-selected payload/test arguments."""
    command([sys.executable, 'Apple/testbed', 'clone', '--platform', 'iOS',
             '--framework', str(framework), str(testbed)], cache, 180)
    receipt = adapt(testbed)
    shutil.copytree(payload, testbed / 'iOSTestbed/app', dirs_exist_ok=True)
    spec = importlib.util.spec_from_file_location('build_manager_owned_testbed', testbed / '__main__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.update_test_plan(testbed, 'iOS', list(test_args))
    return receipt


def ios_build_command(testbed, device, *, deployment_target):
    return ['xcodebuild', '-project', str(testbed / 'iOSTestbed.xcodeproj'), '-scheme', 'iOSTestbed',
            '-destination', 'platform=iOS Simulator,id=' + device,
            '-derivedDataPath', str(testbed / 'DerivedData'), '-parallel-testing-enabled', 'NO',
            'IPHONEOS_DEPLOYMENT_TARGET=' + deployment_target]


def install_payload_wheels(workspace, payload, wheels, requirements, *, command):
    """Install only caller-selected packages from an already verified wheel cache."""
    command([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels),
             '--target', str(payload), '--no-deps', *requirements], workspace, 180)


def android_test_command(serial, payload, test_args):
    return [sys.executable, 'Android/android.py', 'test', '--connected', serial,
            '--site-packages', str(payload), '--', *test_args]
