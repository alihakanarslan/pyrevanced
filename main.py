from atexit import register
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import PriorityQueue
from shutil import rmtree
from subprocess import Popen, PIPE
from tempfile import TemporaryDirectory
from time import perf_counter

from requests import Session
from selectolax.lexbor import LexborHTMLParser

temp_dir = TemporaryDirectory()
temp_folder = Path(temp_dir.name)
session = Session()
session.headers['User-Agent'] = 'Mozilla'


class Downloader:
    _QUEUE = PriorityQueue()
    _QUEUE_LENGTH = 0

    @classmethod
    def _download(cls, url: str, file_name: str) -> None:
        cls._QUEUE_LENGTH += 1
        start = perf_counter()
        with temp_folder.joinpath(file_name).open('wb') as dl_file:
            dl_file.write(session.get(url).content)
        cls._QUEUE.put((perf_counter() - start, file_name))

    @classmethod
    def apkmirror(cls, version: str, music: bool) -> None:
        app = 'youtube-music' if music else 'youtube'
        version = '-'.join(v.zfill(2 if i else 0) for i, v in enumerate(version.split('.')))

        page = 'https://www.apkmirror.com/apk/google-inc/{a}/{a}-{v}-release/{a}-{v}-android-apk-download/'
        parser = LexborHTMLParser(session.get(page.format(v=version, a=app)).text)

        resp = session.get('https://www.apkmirror.com' + parser.css_first('a.accent_bg').attributes['href'])
        parser = LexborHTMLParser(resp.text)

        href = parser.css_first('p.notes:nth-child(3) > span:nth-child(1) > a:nth-child(1)').attributes['href']
        cls._download('https://www.apkmirror.com' + href, 'youtube.apk')

    @classmethod
    def repository(cls, name: str) -> None:
        resp = session.get(f'https://github.com/revanced/revanced-{name}/releases/latest')
        parser = LexborHTMLParser(resp.text)
        url = parser.css('li.Box-row > div:nth-child(1) > a:nth-child(2)')[:-2][-1].attributes['href']
        cls._download('https://github.com' + url, Path(url).with_stem(name).name)

    @classmethod
    def report(cls) -> None:
        started = False
        while True:
            item = cls._QUEUE.get()
            print(f'{item[1]} downloaded in {item[0]:.2f} seconds.')
            cls._QUEUE.task_done()
            cls._QUEUE_LENGTH -= 1

            if not started:
                started = True
            elif started and not cls._QUEUE_LENGTH:
                break


class Patches:
    def __init__(self):
        resp = session.get('https://raw.githubusercontent.com/revanced/revanced-patches/main/README.md')
        available_patches = []
        for line in resp.text.splitlines():
            patch = line.split('|')[1:-1]
            if len(patch) == 4:
                available_patches.append([x.strip().replace('`', '') for x in patch])

        youtube, music = [], []
        for n, d, a, v in available_patches[2:]:
            patch = {'name': n, 'description': d, 'app': a, 'version': v}
            music.append(patch) if 'music' in a else youtube.append(patch)

        self._yt = youtube
        self._ytm = music

    def get(self, music: bool):
        patches = self._ytm if music else self._yt
        version = next(i['version'] for i in patches if i['version'] != 'all')
        return patches, version


class ArgParser:
    _EXCLUDED_PATCHES = []

    @classmethod
    def exclude(cls, name: str) -> None:
        cls._EXCLUDED_PATCHES.extend(['-e', name])

    @classmethod
    def run(cls, output: str = 'revanced.apk') -> None:
        args = ['-jar', '-a', '-o', '-b', '-m']
        files = ['cli.jar', 'youtube.apk', 'revanced.apk', 'patches.jar', 'integrations.apk']
        args = [v for i in zip(args, map(lambda i: temp_folder.joinpath(i), files)) for v in i]

        if cls._EXCLUDED_PATCHES:
            args.extend(cls._EXCLUDED_PATCHES)

        process = Popen(['java', *args], stdout=PIPE)
        for line in process.stdout:
            print(line.decode(), flush=True, end='')
        process.wait()

        apk = temp_folder.joinpath('revanced.apk')
        target = Path.cwd().joinpath(output)
        if target.is_file():
            target.unlink()
        apk.rename(target)


@register
def close():
    session.close()
    temp_dir.cleanup()
    cache = Path('revanced-cache')
    if cache.is_dir():
        rmtree(cache)


def main():
    patches = Patches()
    downloader = Downloader
    arg_parser = ArgParser

    def get_patches():
        for i, v in enumerate(app_patches):
            print(f'[{i:>02}] {v["name"]:<32}: {v["description"]}')

        selected_patches = input('Select the patches you want as "0 2 1 ...": ').split(' ')
        selected_patches = list(set(map(int, [i.strip() for i in selected_patches if i.strip() and i.isdigit()])))

        if any(not 0 <= x < len(app_patches) for x in selected_patches):
            raise Exception('Some of the selected patches are not valid.')

        selected_patches = [v['name'] for i, v in enumerate(app_patches) if i not in selected_patches]
        for sp in selected_patches:
            arg_parser.exclude(sp)

    app = input('Youtube or Youtube Music? [YT/YTM]: ').lower().strip()
    if app not in ('yt', 'ytm'):
        raise Exception(f'{app} is not valid choice.')
    app_patches, version = patches.get((music := app == 'ytm'))

    with ThreadPoolExecutor() as executor:
        executor.map(downloader.repository, ('cli', 'integrations', 'patches'))
        executor.submit(downloader.apkmirror, version, music)
        executor.submit(get_patches).add_done_callback(lambda _: downloader.report())
    print('Download completed.')

    arg_parser.run()
    print('Wait for programme to exit.')


if __name__ == '__main__':
    main()
