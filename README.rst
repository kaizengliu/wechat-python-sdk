微信公众平台 Python 开发包
===========================

* 本开发包在`wechat-python-sdk<https://github.com/doraemonext/wechat-python-sdk>`_ 项目基础上构建的
* wechat-python-sdk项目文档: `http://wechat-python-sdk.readthedocs.org/ <http://wechat-python-sdk.readthedocs.org/>`_
* 添加或修改的功能如下:
  * 更改grant_token存储方式, 以memcache代替原来的变量存储方式. 原来WechatBasic将grant_token以私有变量存储，在服务重启时会使grant_token实效，
    当有多个服务同时运行时，每个服务的grant_token会不一致，导致grant_token的频繁更新。
  * "网页授权获取用户基本信息"的snsapi_base方式
  * 微信支付


文档
----------------------------

`http://wechat-python-sdk.readthedocs.org/ <http://wechat-python-sdk.readthedocs.org/>`_

快速开始
----------------------------

安装
^^^^^^^^^^^^^^^^^^^^^^^^^^^^


快速上手文档
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`http://wechat-python-sdk.readthedocs.org/zh_CN/master/tutorial.html <http://wechat-python-sdk.readthedocs.org/zh_CN/master/tutorial.html>`_
