from __future__ import annotations

from dataclasses import dataclass
import enum
import logging
from contextlib import ExitStack
from datetime import datetime
from functools import reduce
from pathlib import Path, PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)


from serialtek.tasks import PolledTask, WaitParams
from serialtek.util import Json
from serialtek.util.json import get_as

from .util import validate_response

if TYPE_CHECKING:

    from requests import Response
    from typing_extensions import Self

    from .kodiak import Kodiak
    from .types import Readable, Writeable

log: logging.Logger = logging.getLogger(__name__)

R = TypeVar("R")


class KodiakPath(PurePosixPath):
    """A path representing a file on a Kodiak.

    :py:class:`.KodiakPath` provides `pathlib.Path
    <https://docs.python.org/3/library/pathlib.html>`_ - like functionality for working
    with files on a Kodiak. To create a KodiakPath, use
    :py:attr:`.Kodiak.Path`::

        >>> p = kodiak.Path("/media/NVMeDrive0/my_trace.sttrace")
        >>> p.exists()
        True
        >>> print(p.parent)
        /media/NVMeDrive0
        >>> print(p.parent/"folder_name")
        /media/NVMeDrive0/folder_name

    Kodiak paths must be absolute, and must start with ``/media``.

    All :py:class:`PurePath` methods (ie, simple path manipulation without file access)
    are supported. Many methods specific to concrete paths (methods that require access
    to the file system) are available as well, those are documented here.
    """

    # This is a class member that is set on child classes to allow access to the
    # Kodiak for file system operations. See _make_bound() below.
    _kodiak: Kodiak

    def __new__(cls, *args: Any) -> Self:
        if not hasattr(cls, "_kodiak"):
            msg = (
                "KodiakPath cannot be instantiated directly: Open a Kodiak and use"
                " `Kodiak.Path()`"
            )
            raise TypeError(msg)
        return super().__new__(cls, *args)

    def __init__(self, *args: Any):
        # On some versions of python PurePosixPath has an __init__ method that we need
        # to call. However, on the ones that don't, calling __init__ will cause an
        # error. Check if PurePosixPath has overridden the default init.
        if PurePosixPath.__init__ is not object.__init__:
            PurePosixPath.__init__(self, *args)
        s = str(self)
        if not s.startswith("/media"):
            msg = (
                "All KodiakPath values must be absolute and start with /media,"
                f" {s!r} is invalid"
            )
            raise ValueError(msg)

    @staticmethod
    def _make_bound(kodiak: Kodiak) -> Type[KodiakPath]:
        """Create a bound version of this class which can be accessed via Kodiak.Path.

        The KodiakPath class is never actually instantiated directly--the only way to
        get one is through a Kodiak. The Kodiak object creates its own subclass of
        KodiakPath, specific to that Kodiak and with a reference back to it. It does
        so using this method.

        :meta private:
        """

        class _BoundKodiakPath(KodiakPath):
            _kodiak = kodiak

        _BoundKodiakPath.__name__ = "KodiakPath"

        return _BoundKodiakPath

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Create a path from the URI path used to access it.

        :meta private:
        """
        path = uri.removeprefix("/kodiak/v1")
        return cls(path)

    @property
    def uri(self) -> str:
        """The full URI of this file."""
        return f"/kodiak/v1/{self}"

    def _get_info(self, *, recurse: Union[bool, int] = False) -> Json:
        """Get the file info for this file from the API."""
        if recurse is True:
            params = {"recursive": "true"}
        elif recurse is False:
            params = {}
        else:
            params = {"depth": recurse}

        resp = self._kodiak.session.get(self.uri, params=params)
        if resp.status_code == 404:
            raise FileNotFoundError(self.uri)
        return resp.validate().json()

    def stat(self) -> Stat:
        """Get information on this file or directory."""
        if str(self) == "/media":
            # /media isn't really a directory, so we can't use _get_info() on it. The
            # stat for it is trivial though, just indicating that it's the root.
            return Stat(type=FileType.ROOT)
        info = self._get_info()
        return Stat.from_info(info)

    def exists(self) -> bool:
        """Return whether a file or directory exists at this path."""
        try:
            self.stat()
        except FileNotFoundError:
            return False
        else:
            return True

    def is_dir(self) -> bool:
        """Return whether a directory exists at this path."""
        try:
            return self.stat().is_dir
        except FileNotFoundError:
            return False

    def is_file(self) -> bool:
        """Return whether a file exists at this path."""
        try:
            return self.stat().is_file
        except FileNotFoundError:
            return False

    def iterdir(
        self,
        *,
        folders: bool = True,
        files: bool = True,
        recurse: Union[bool, int] = False,
    ) -> Iterable[Self]:
        """Iterate over all files and folders in this directory.

        :param folders: Set to False to exclude folders from the output.
        :param files: Set to False to exclude files from the output.
        :param recursive: Include the contents of all folders recursively. This can be
            ``True`` to recurse all the way down, or an integer indicating how many
            levels of folders to open.
        """
        idir = self.iterdir_stat(recurse=recurse)
        for path, stat in idir:
            if (stat.is_file and files) or (stat.is_dir and folders):
                yield path

    def iterdir_stat(
        self, *, recurse: Union[bool, int] = False
    ) -> Iterable[Tuple[Self, Stat]]:
        """Iterate over all files and folder in a directory.

        This does the same thing as :py:meth:`iterdir`, but it returns both an
        :py:class:`.KodiakPath` and a :py:class:`Stat`.
        """
        if str(self) == "/media":
            # /media works a bit differently, since it's not really a directory, but we
            # can return a list of mount points.
            resp = self._kodiak.session.get(self.uri)
            validate_response(resp)
            resp = resp.json()
            for entry in resp["members"]:
                p = self.from_uri(entry["uri"])
                yield p, Stat(type=FileType.DEVICE)
                if recurse:
                    r = True if recurse is True else recurse - 1
                    yield from p.iterdir_stat(recurse=r)
            return

        info = self._get_info(recurse=recurse)

        match info:
            case {"root": f}:
                folder = f
            case {"files": _, "folders": _}:
                folder = info
            case _:
                raise NotADirectoryError(self.uri)

        def yield_folder(folder: Json) -> Iterable[Tuple[Self, Stat]]:
            for info in folder["folders"]:
                stat = Stat.from_info(info)
                yield type(self).from_uri(info["path"]), stat
                if stat.is_dir:
                    yield from yield_folder(info)

            for info in folder["files"]:
                yield type(self).from_uri(info["path"]), Stat.from_info(info)

        yield from yield_folder(folder)

    def mkdir(self, *, parents: bool = False, exist_ok: bool = False) -> None:
        """Create the directory indicated by this path.

        If ``parents`` is True, any missing parents of this path are created as needed.
        If ``parents`` is False, a missing parent will raise
        :py:exc:`FileNotFoundError`.

        If ``exist_ok`` is False and anything exists at the target location,
        :py:exc:`FileExistsError` will be raised. If ``exist_ok`` is True,
        :py:exc:`FileExistsError` will be ignored unles the existing file is not a
        directory.

        :param exist_ok: Do not raise an error if the
        """
        if not parents and not self.parent.exists():
            msg = f"Parent directory {self.parent} for mkdir does not exist"
            raise FileNotFoundError(msg)

        try:
            self.stat()
            if self.stat().is_dir and exist_ok:
                log.info("Skip create directory %s as it already exists.", self)
                return
            else:
                msg = f"{self} already exists."
                raise FileExistsError(msg)
        except FileNotFoundError:
            pass

        resp = self._kodiak.session.post(
            "/kodiak/v1/media/create_folder",
            json={"path": str(self)},
        )
        validate_response(resp)
        log.info("Created directory %s", self)

    @overload
    def rename(
        self,
        target: Union[str, PurePosixPath],
        *,
        overwrite: bool = ...,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> Self:
        ...

    @overload
    def rename(
        self,
        target: Union[str, PurePosixPath],
        *,
        overwrite: bool = ...,
        wait: Literal[False],
    ) -> Self:
        ...

    def rename(
        self,
        target: Union[str, PurePosixPath],
        *,
        overwrite: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[Self, MediaTask[Self]]:
        """Rename this file or folder.

        :param overwrite: Whether to overwrite the target if it already exists.
        :param wait: Whether to wait for the task to finish, or parameters to use when
            waiting.

        :return: The new path to the file. If ``wait`` is set to False, a
            :py:class:`.MediaTask` will be returned instead; call
            :py:meth:`~.MediaTask.join` to wait for the task to finish and get the
            result.
        """
        stat = self.stat()

        if stat.type == FileType.DIR:
            url = "/kodiak/v1/media/move_folder"
        elif stat.type == FileType.FILE:
            url = "/kodiak/v1/media/move_file"
        else:
            msg = f"{self} cannot be renamed."
            raise ValueError(msg)

        resp = self._kodiak.session.post(
            url,
            json={
                "path": str(self),
                "new_path": str(target),
                "overwrite": str(overwrite),
            },
        ).validate(success_code=[200, 202])
        resp_json = resp.json()

        return MediaTask(
            resp,
            f"Move {self} to {target}",
            type(self)(resp_json["new_path"]),
            self._kodiak,
        ).maybe_wait(wait)

    def rmdir(self, *, missing_ok: bool = False, recursive: bool = False) -> None:
        """Delete a directory.

        The directory must be empty unless ``recursive`` is set to True. Use
        :py:meth:`unlink` for files.

        :param missing_ok: Don't raise an exception if the directory doesn't exist.
        :param recursive: Delete all files in the directory if it isn't empty.
        """
        try:
            if not self.stat().is_dir:
                raise NotADirectoryError(self.uri)
        except FileNotFoundError:
            if missing_ok:
                log.info("Delete %s: Directory does not exist", self)
                return
            else:
                raise

        resp = self._kodiak.session.post(
            "/kodiak/v1/media/delete_folder",
            json={"path": str(self), "recursive": recursive},
        )
        validate_response(resp)
        log.info("Deleted directory %s", self)

    def unlink(self, *, missing_ok: bool = False) -> None:
        """Delete a file.

        use :py:meth:`unlink` for directories.

        :param missing_ok: Don't raise an exception if the file doesn't exist.
        """
        try:
            if not self.stat().is_file:
                raise NotADirectoryError(self.uri)
        except FileNotFoundError:
            if missing_ok:
                log.info("Delete %s: File does not exist", self)
                return
            else:
                raise

        self._kodiak.session.post(
            "/kodiak/v1/media/delete_file",
            json={"path": str(self)},
        ).validate()
        log.info("Deleted file %s", self)

    def permalink(self, *, path_only: bool = False) -> str:
        """Get a permanent download link to this file that can be shared."""
        # stat() the file, just to make sure it exists
        self.stat()
        resp = (
            self._kodiak.session.post(
                "/kodiak/v1/media/link",
                data={"path": str(self)},
            )
            .validate()
            .json()
        )
        if path_only:
            return resp["link"]
        else:
            return f"{self._kodiak.session.host}{resp['link']}"

    @overload
    def copy(
        self,
        target: KodiakPath,
        *,
        recursive: bool = ...,
        overwrite: bool = ...,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> Self:
        ...

    @overload
    def copy(
        self,
        target: KodiakPath,
        *,
        recursive: bool = ...,
        overwrite: bool = ...,
        wait: Literal[False],
    ) -> MediaTask[Self]:
        ...

    def copy(
        self,
        target: KodiakPath,
        *,
        recursive: bool = False,
        overwrite: bool = False,
        wait: Union[WaitParams, bool] = True,
    ) -> Union[Self, MediaTask[Self]]:
        """Copy this file or folder.

        :param overwrite: Whether to overwrite the target if it already exists.
        :param recursive: If a directory is being copied, this determines whether to
            copy the contents as well.
        :param wait: Whether to wait for the task to finish, or parameters to use when
            waiting.

        :return: The path to the copied file. If ``wait`` is set to False, a
            :py:class:`.MediaTask` will be returned instead; call
            :py:meth:`~.MediaTask.join` to wait for the task to finish and get the
            result.
        """
        stat = self.stat()

        if stat.type == FileType.DIR:
            url = "/kodiak/v1/media/copy_folder"
        elif stat.type == FileType.FILE:
            url = "/kodiak/v1/media/copy_file"
        else:
            msg = f"{self} cannot be copied."
            raise ValueError(msg)

        resp = self._kodiak.session.post(
            url,
            json={
                "path": str(self),
                "new_path": str(target),
                "overwrite": overwrite,
                "recursive": recursive,
            },
        )
        validate_response(resp, success_code=[200, 202])
        resp_json = resp.json()

        return MediaTask(
            resp,
            f"Copy {self.name}",
            type(self)(resp_json["new_path"]),
            self._kodiak,
        ).maybe_wait(wait)

    def download(
        self,
        target: Union[str, Path, Writeable],
        *,
        progress: Optional[Callable[[int, int, int], Optional[bool]]] = None,
        chunk_size: int = 8192,
    ) -> bool:
        """Download this file from the Kodiak.

        The target argument indicates what to do with the download. This can be:

            * A string or ``Path`` (local path, not :py:class:`KodiakPath`). The
              indicated file will be opened and written to.
            * An open file in binary mode.
            * Anything with a :py:meth:`~.Writeable.write` method, which will be called
              repeatedly with the chunks of the data.

        The most common use case is to simply download a file from the Kodiak to the
        local file system::

            >>> p = kodiak.Path("/media/NVMeDrive0/download-file.sttrace")
            >>> p.download("local/path/download-file.sttrace")

        :param progress: An optional progress callback. This will be called for each
            chunk, with three arguments: the size of the last chunk, the total number of
            bytes transferred, and the total number of bytes in the file. If this
            function returns True, the download will be cancelled.
        :param chunk_size: The target chunk size. This is not a hard setting: chunks may
            be larger or smaller than this value.

        :return: ``True`` if the download was cancelled, otherwise ``False``.
        """
        with ExitStack() as es:
            if isinstance(target, (str, Path)):
                stream = es.push(open(target, "wb"))
            else:
                stream = target

            resp = es.push(
                self._kodiak.session.get(
                    self.uri, stream=True, params={"download": "true"}
                )
            )
            validate_response(resp)

            total = int(resp.headers["content-length"])
            received = 0
            if progress and progress(0, 0, total):
                return True
            for chunk in resp.iter_content(chunk_size=chunk_size):
                stream.write(chunk)
                received += len(chunk)
                if progress and progress(len(chunk), received, total):
                    return True
        log.info("Downloaded file %s to %s", self, target)
        return False

    def upload(
        self,
        source: Union[str, Path, Readable],
        *,
        progress: Optional[Callable[[int, int, int], Optional[bool]]] = None,
        size: Optional[int] = None,
        chunk_size: int = 8192,
    ) -> bool:
        """Upload a file to the Kodiak to this path.

        The source argument indicates where to get the data to upload. This can be:

            * A string or ``Path`` (local path, not :py:class:`KodiakPath`). The
              indicated file will be opened and read.
            * An open file in binary mode. If this is the case, the size of the data to
              send needs to be provided with the ``size`` argument.
            * Anything with a :py:meth:`~.Readable.read` method, which will be called
              repeatedly to get the data to send. If this is the case, the size of the
              data to send needs to be provided with the ``size`` argument.

        The most common use case is to simply upload a file from the local file system
        to the Kodiak::

            >>> p = kodiak.Path("/media/NVMeDrive0/upload-file.sttrace")
            >>> p.upload("local/path/upload-file.sttrace")

        :param progress: An optional progress callback. This will be called for each
            chunk, with three arguments: the size of the last chunk, the total number of
            bytes transferred, and the total number of bytes in the file. If this
            function returns True, the download will be cancelled.
        :param size: The total size of the file. This is only needed if ``source`` is
            not
        :param chunk_size: The size to use for each chunk sent.

        :return: ``True`` if the download was cancelled, otherwise ``False``.
        """
        with ExitStack() as es:
            if isinstance(source, (str, Path)):
                source = Path(source)
                size = source.stat().st_size
                stream = open(source, "rb")
            else:
                stream = source

            if size is None:
                msg = (
                    f"Cannot determine the size of {type(source)} for upload, specify"
                    " the size as an argument to this function."
                )
                raise ValueError(msg)

            # Start the upload
            resp = (
                self._kodiak.session.post(
                    "/kodiak/v1/media/upload",
                    json={"path": str(self), "size": size},
                )
                .validate()
                .json()
            )
            upload_id = resp["id"]

            # Make sure we cancel this upload when we're done, one way or another.
            es.callback(
                lambda: self._kodiak.session.delete(
                    f"/kodiak/v1/media/upload/{upload_id}"
                )
            )

            sent = 0
            if progress and progress(0, 0, size):
                return True
            while sent <= size:
                data = stream.read(chunk_size)
                self._kodiak.session.post(
                    f"/kodiak/v1/media/upload/{upload_id}/chunk",
                    files={"file": ("blob", data, "application/octet-stream")},
                ).validate()
                sent += len(data)
                if progress and progress(len(data), sent, size):
                    return True
                if len(data) < chunk_size:
                    break
        log.info("Uploaded %s as %s", source, self)
        return False

    @overload
    def compress(
        self,
        *,
        keep_original: bool = True,
        wait: Union[WaitParams, Literal[True]] = True,
    ) -> Self:
        ...

    @overload
    def compress(
        self, *, keep_original: bool = True, wait: Union[WaitParams, Literal[False]]
    ) -> CompressionTask:
        ...

    def compress(
        self, *, keep_original: bool = True, wait: Union[WaitParams, bool] = True
    ) -> Union[KodiakPath, CompressionTask]:
        """Compress a file on the file system.

        :param keep_original: If this is set to False, the original file will be deleted
            when compression is complete.
        :param wait: Whether to wait for the task to finish, or parameters to use when
            waiting.

        :return: The path to the compressed file. If ``wait`` is set to False, a
            :py:class:`.CompressionTask` will be returned instead; call
            :py:meth:`~.CompressionTask.join` to wait for the task to finish and get the
            result.
        """
        # Stat the file, just to make sure it exists
        self.stat()

        dest = self.with_name(self.name + ".gz")
        if dest.exists():
            msg = f"Compressing {self} would create {dest}, which already exists"
            raise FileExistsError(msg)

        resp = (
            self._kodiak.session.post(
                "/kodiak/v1/media/compression_queue",
                json={"path": str(self), "keep_original": keep_original},
            )
            .validate(success_code=[201])
            .json()
        )

        return CompressionTask(
            resp["index"],
            self,
            dest,
            self._kodiak,
        ).maybe_wait(wait)


class FileType(enum.Enum):
    """The different types of files that are available"""

    #: A file
    FILE = "file"
    #: A directory
    DIR = "directory"
    #: The root of a mounted drive
    DEVICE = "device"
    #: Used for the read-only special root path, ``/media``
    ROOT = "root"


@dataclass
class Stat:
    """Information on a file or directory."""

    #: The type of the file/directory
    type: FileType
    #: Size of the file/directory in bytes
    size: Optional[int] = None
    #: When the file/directory was created
    created: Optional[datetime] = None
    #: When the file/directory was accessed
    accessed: Optional[datetime] = None
    #: When the file/directory was last modified
    modified: Optional[datetime] = None

    @classmethod
    def from_info(cls, info: Json) -> Self:
        """Create a :py:class:`.Stat` object from a raw API response."""
        match info:
            case {"root": _}:
                # This is a media device
                return cls(type=FileType.DEVICE)
            case {"size": int(size)}:
                return cls(
                    type=FileType.FILE,
                    size=size,
                    created=get_as(info, datetime, "created"),
                    accessed=get_as(info, datetime, "accessed"),
                    modified=get_as(info, datetime, "modified"),
                )
            case _:
                return cls(
                    type=FileType.DIR,
                    created=get_as(info, datetime, "created"),
                    accessed=get_as(info, datetime, "accessed"),
                    modified=get_as(info, datetime, "modified"),
                )

    @property
    def is_dir(self) -> bool:
        """Whether this info is for a directory"""
        return self.type in (FileType.DIR, FileType.DEVICE, FileType.ROOT)

    @property
    def is_file(self) -> bool:
        """Whether this info is for a file"""
        return self.type == FileType.FILE


class MediaTask(PolledTask[R]):
    """A representation of a media task that the Kodiak is doing in the background.

    This class is returned by several operations performed using
    :py:class:`~serialtek.path.Path` when ``wait`` is set to ``False``.
    """

    task_id: int
    result: R
    kodiak: Kodiak

    def __init__(self, resp: Response, desc: str, result: R, kodiak: Kodiak):
        super().__init__(desc)
        self.kodiak = kodiak
        self.task_id = resp.json()["id"]
        self.result = result

    def _poll(self) -> float:
        """Get the progress of this task as a percentage."""
        resp = self.kodiak.session.get(f"/kodiak/v1/media/tasks/{self.task_id}")
        if resp.status_code == 404:
            return 100
        else:
            validate_response(resp)
            progress = resp.json()["progress"]
            if progress >= 100:
                self.kodiak.session.delete(f"/kodiak/v1/media/tasks/{self.task_id}")
            return progress

    def _get_result(self) -> R:
        return self.result


class CompressionTask(PolledTask[KodiakPath]):
    """Representation of a compression that the Kodiak is doing in the background.

    This class is returned by several operations performed using
    :py:meth:`~.Path.compress` when ``wait`` is set to ``False``.
    """

    id: int
    source: KodiakPath
    dest: KodiakPath
    kodiak: Kodiak

    def __init__(
        self, id: int, source: KodiakPath, dest: KodiakPath, kodiak: Kodiak
    ):
        self.id = id
        self.source = source
        self.dest = dest
        self.kodiak = kodiak
        super().__init__(f"Wait for compression of {self.source}")

    def _poll(self) -> float:
        """Get the progress of this task as a percentage."""
        resp = self.kodiak.session.get(
            f"/kodiak/v1/media/compression_queue/{self.id}"
        )
        if resp.status_code == 404:
            return 100
        else:
            progress = resp.json()["progress"]
            if progress >= 100:
                self.kodiak.session.delete(
                    f"/kodiak/v1/media/compression_queue/{self.id}"
                )
            return progress

    def _get_result(self) -> KodiakPath:
        return self.dest


S = TypeVar("S", Path, KodiakPath)
D = TypeVar("D", Path, KodiakPath)


class FileTransferOps(Generic[S, D]):
    """Helper class for determining/validating all the file transfers for an operation.

    This class provides similar file selection semantics to the `mv` or `cp` commands:

    * One or many source paths can be given, but only one destination path is accepted.
    * If the destination is a directory, The destination for the source files will be
      ``<destination>/<source_filename>``.
    * If the destination is a file, the exact filename will be used for the destination.
      This is only allowed if there is only one source file.

    The file operations will all be determined and checked when this class is created.
    To get the list of files to transfer, use :py:meth:`files`::

        >>> transfers = FileTransferOps(
            [Path("a.txt"), Path("b.txt")], Path("c_dir")
        ) >>> transfers.dir c_dir >>> transfers.dir.mkdir(exist_ok=True) >>> for source,
        dest in transfers.files(): ...     print(f"move {source} to {dest}") ...
        source.rename(dest) move a.txt to c_dir/a.txt move b.txt to c_dir/b.txt


    This class can be used with :py:class:`Path` objects representing local files,
    :py:class:`KodiakPath` objects, or a mix of the two, as long as all source paths
    are of the same type.

    :param recursive: If this is False, :py:exc:`IsADirectoryError` Whether to allow
        directories in the input. How the directories are handled is determined by the
        ``expand`` argument.
    :param overwrite: If this is False, :py:exc:`FileExistsError` will be raised if any
        of the destination paths already exist.
    :param expand: Determines the handling of directories when ``recursive`` is True. If
        ``expand`` is False, then :py:meth:`files` will yield a single operation for the
        entire folder. If it is True, then :py:meth:`files` will yield a path for every
        file within the directory (but not for any directories themselves). For example,
        considering the following file structure::

            src_dir/
              a.txt b.txt inner_dir/
                c.txt

        The following behavior can be expected::

            >>> noexpand = FileTransferOps([Path("src_dir")], Path("dest_dir"), recursive=True, expand=False)
            >>> list(noexpand)
            [(Path("src_dir"), Path("dest_dir/src_dir"))]
            >>> expand = FileTransferOps([Path("src_dir")], Path("dest_dir"), recursive=True, expand=True)
            >>> list(expand)
            [
                (Path("src_dir/a.txt"), Path("dest_dir/src_dir/a.txt")),
                (Path("src_dir/b.txt"), Path("dest_dir/src_dir/b.txt")),
                (Path("src_dir/inner_dir/a.txt"), Path("dest_dir/src_dir/inner_dir/a.txt"))
            ]
    """

    #: The directory in which this operation will take place. All destination paths will
    #: be within this directory. If ``expand`` is True, some destination paths may be in subdirectories of this one.
    dir: D
    _ops: Dict[D, S]

    def __str__(self) -> str:
        return "\n".join(f"{s} -> {d}" for s, d in self.files())

    def __init__(
        self,
        sources: List[S],
        dest: D,
        *,
        recursive: bool = False,
        overwrite: bool = False,
        expand: bool = False,
    ):
        ops: Dict[D, S] = {}
        dest_is_dir: bool

        if len(sources) == 0:
            msg = "At least two paths (source/destination) are needed."
            raise ValueError(msg)

        if len(sources) > 1:
            if dest.is_file():
                msg = (
                    "The destination must be a directory (or not exist) when operating"
                    f" on multiple files, {dest} is a file."
                )
                raise FileExistsError(msg)
            dest_is_dir = True
        else:
            dest_is_dir = dest.is_dir()
        self.dir = dest if dest_is_dir else dest.parent

        for source_path, dest_subpath in self._source_paths(
            sources, recursive=recursive, expand=expand
        ):
            if dest_is_dir:
                dest_path = reduce(lambda x, y: x / y, dest_subpath, dest)
            else:
                dest_path = dest

            if dest_path in ops and ops[dest_path] != source_path:
                msg = (
                    f"Both {source_path} and {ops[dest_path]} target the same"
                    f" destination path {dest_path}"
                )
                raise ValueError(msg)

            if not overwrite and dest_path.exists():
                msg = f"{dest_path} already exists, and overwriting is not enabled."
                raise FileExistsError(msg)

            ops[dest_path] = source_path
        self._ops = ops

    @classmethod
    def _source_paths(
        cls,
        source: Iterable[S],
        recursive: bool,
        expand: bool,
        base: Tuple[str, ...] = (),
    ) -> Iterable[Tuple[S, Tuple[str, ...]]]:
        for source_path in source:
            src_exists, src_is_dir = cls._path_state(source_path)

            if not src_exists:
                msg = f"{source_path} does not exist."
                raise FileNotFoundError(msg)

            if not recursive and src_is_dir:
                msg = f"{source_path} is a directory, and recursion is not enabled."
                raise IsADirectoryError(msg)

            if expand and src_is_dir:
                yield from cls._source_paths(
                    source_path.iterdir(),
                    recursive=recursive,
                    expand=expand,
                    base=(*base, source_path.name),
                )
            else:
                yield source_path, (
                    *base,
                    source_path.name,
                )

    @classmethod
    def _path_state(cls, path: S) -> Tuple[bool, bool]:
        """Return (exists, is_dir) for the given path."""
        if isinstance(path, KodiakPath):
            try:
                stat = path.stat()
                return True, stat.is_dir
            except FileNotFoundError:
                return False, False
        else:
            return path.exists(), path.is_dir()

    def files(self) -> Iterable[Tuple[S, D]]:
        """Iterate over all of the source/destination pairs in this operation."""
        for d, s in self._ops.items():
            yield s, d
