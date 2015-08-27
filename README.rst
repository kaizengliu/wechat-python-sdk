微信公众平台 Python 开发包
===========================

* 本开发包是在 `wechat-python-sdk <https://github.com/doraemonext/wechat-python-sdk/>`_ 项目基础上构建的
* wechat-python-sdk项目文档: `http://wechat-python-sdk.readthedocs.org/ <http://wechat-python-sdk.readthedocs.org/>`_
* 添加或修改的功能如下:

  * 更改grant_token存储方式, 以memcache代替原来的变量存储方式. 并建议以单利模式方式使用微信类(微信类所需的如appid等众多参数没有必要因为微信类实例的重复新建再写一次)。原来WechatBasic将grant_token以私有变量存储，使用单例模式时，在服务重启时会使grant_token失效。当有多个服务同  时运行时，每个服务的grant_token会不一致，导致grant_token的频繁更新。
  * 网页授权获取用户基本信息的snsapi_base方式
  * 微信支付(扫描，jsapi)


文档
----------------------------
 * 单例模式, wechat.py文件::
 
    import setting
    import memcache

    from wechat_sdk import WechatBasic

    memcache_client = memcache.Client(setting.MEMCACHED_MACHINES)

    wechat = WechatBasic(memcache_client, token=setting.token, appid=setting.WEIXIN_APP_ID,
                      appsecret=setting.WEIXIN_APP_SECRET, mch_id=setting.WEIXIN_MCH_ID, api_key=setting.WEIXIN_API_KEY)

   # 在需要使用微信功能的地方，从wechat引入wechat示例即可
   # 此外，如果需要更改access_token存储方式，可以写一个Wechat类继承WeChatBasic，重写__init__,
   grant_token, access_token方法即可。本项目会在后期创建一个存储access_token的类，提供统一的
   # 存储access_token的接口，以兼容用mysql, redis, memcache, mongodb等方式存储access_token

 * 主要功能详情：`http://wechat-python-sdk.readthedocs.org/ <http://wechat-python-sdk.readthedocs.org/>`_
 * 网页授权::

    from wechat import wechat

    # ...省略
    menu_data = {
        "button": [
         {
            "name": "业务介绍",
            "type": "view"
            "url":  service_desc_url
         },

         {
            "name": "下单",
            "type": "view",
            "url":  wechat.web_authorize_url(order_url) # order_url需为绝对路径
         }
       ]
    }

    wechat.create_menu(menu_data)

 * 支付
 
   * 二维码支付::

     from wechat import wechat

     # unified_order参数详情请查看代码
     wechat_ret = WeiXin.unified_order(
         "超级电器", 10223434, 20000,
         "125.39.240.113", notify_url, 'NATIVE', '1232423423423')
     )

     code_url = wechat_ret.get("code_url")
     # 将code_url返回到前端，用二维码生成工具生成二维码, 即可通过扫描二维码进行支付
     # 支付成功后, notifiy_url会收到微信服务器的通知


   * js支付::

     from wechat import wechat

     # unified_order参数详情请查看代码
     wechat_ret = WeiXin.unified_order(
        "超级电器", 10223434, 20000,
        "125.39.240.113", notify_url, 'JSAPI', '1232423423423')
     )

     prepay_id = wechat_ret.get("prepay_id")
     jsapi_params = WeiXin.generate_jsapi_pay_params(prepay_id)

     # 将jsapi_params返回到前端(微信页面), 参照`微信支付文档<https://pay.weixin.qq.com/wiki/doc/api/jsapi.php?chapter=7_7>`_
     # 调用微信支付js接口进行微信支付即可

安装
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  目前只能下载本开发包，运行python setup.py运行, 目前尚未进行整体测试，新增的微信功能，均在实际中测试过。

