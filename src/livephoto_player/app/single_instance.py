"""单实例运行：``QLocalServer`` + ``QLocalSocket``。

第二个实例把命令行里的文件路径发给已有实例后立即退出，不创建窗口。
"""

from __future__ import annotations

import getpass
import hashlib

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from livephoto_player.utils.logger import get_logger
from livephoto_player.utils.paths import APP_ID


def _server_name() -> str:
    """服务名包含软件名与用户标识，避免多用户互相抢占。"""
    user = getpass.getuser() or "default"
    digest = hashlib.sha256(user.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{APP_ID}-{digest}-instance"


class SingleInstance(QObject):
    """持有本地套接字服务端，并把收到的消息转成信号。"""

    message_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = get_logger("instance")
        self._name = _server_name()
        self._server: QLocalServer | None = None

    def try_acquire(self, payload: str = "") -> bool:
        """尝试成为主实例；返回 ``False`` 表示已有实例在运行。"""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if socket.waitForConnected(400):
            if payload:
                socket.write(payload.encode("utf-8"))
                socket.flush()
                socket.waitForBytesWritten(400)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(self._name):
            self._logger.error("单实例监听失败：%s", self._server.errorString())
            return False
        self._logger.info("单实例服务已就绪：%s", self._name)
        return True

    def close(self) -> None:
        """退出前关闭服务端。"""
        if self._server is not None:
            self._server.close()
            self._server = None

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.waitForReadyRead(500)
        raw = bytes(connection.readAll().data())
        connection.disconnectFromServer()
        message = raw.decode("utf-8", "replace").strip()
        if message:
            self.message_received.emit(message)
