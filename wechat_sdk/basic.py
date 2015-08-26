# -*- coding: utf-8 -*-

import hashlib
import requests
import time
import json
import random
import cgi
import string
from StringIO import StringIO

from xml.dom import minidom

from .messages import MESSAGE_TYPES, UnknownMessage
from .exceptions import ParseError, NeedParseError, NeedParamError, OfficialAPIError
from .reply import TextReply, ImageReply, VoiceReply, VideoReply, MusicReply, Article, ArticleReply
from .lib import disable_urllib3_warning, XMLStore, xml2dict, dict2xml


class WechatBasic(object):
    """
    微信基本功能类

    仅包含官方 API 中所包含的内容, 如需高级功能支持请移步 ext.py 中的 WechatExt 类
    """
    def __init__(self, memcache_client, token=None, appid=None, appsecret=None, partnerid=None, partnerkey=None, paysignkey=None, jsapi_ticket=None,
                 jsapi_ticket_expires_at=None, checkssl=False, mch_id=None, api_key=None):
        """
        :param memcache_client: memcache.Client对象
        :param token: 微信 Token
        :param appid: App ID
        :param appsecret: App Secret
        :param partnerid: 财付通商户身份标识, 支付权限专用
        :param partnerkey: 财付通商户权限密钥 Key, 支付权限专用
        :param paysignkey: 商户签名密钥 Key, 支付权限专用
        :param jsapi_ticket: 直接导入的 jsapi_ticket 值, 该值需要在上一次该类实例化之后手动进行缓存并在此处传入, 如果不传入, 将会在需要时自动重新获取
        :param jsapi_ticket_expires_at: 直接导入的 jsapi_ticket 的过期日期，该值需要在上一次该类实例化之后手动进行缓存并在此处传入, 如果不传入, 将会在需要时自动重新获取
        :param checkssl: 是否检查 SSL, 默认为 False, 可避免 urllib3 的 InsecurePlatformWarning 警告
        :param mch_id: 微信支付分配的商户号
        :param api_key: API密钥
        :param memcache_client:
        """
        if not checkssl:
            disable_urllib3_warning()  # 可解决 InsecurePlatformWarning 警告

        self.__client = memcache_client

        self.__token = token
        self.__appid = appid
        self.__appsecret = appsecret
        self.__partnerid = partnerid
        self.__partnerkey = partnerkey
        self.__paysignkey = paysignkey

        self.__access_token = None
        self.__access_token_expires_at = None
        self.__jsapi_ticket = jsapi_ticket
        self.__jsapi_ticket_expires_at = jsapi_ticket_expires_at
        self.__is_parse = False
        self.__message = None
        self.__mch_id = mch_id
        self.__api_key = api_key

    def check_signature(self, signature, timestamp, nonce):
        """
        验证微信消息真实性
        :param signature: 微信加密签名
        :param timestamp: 时间戳
        :param nonce: 随机数
        :return: 通过验证返回 True, 未通过验证返回 False
        """
        self._check_token()

        if not signature or not timestamp or not nonce:
            return False

        tmp_list = [self.__token, timestamp, nonce]
        tmp_list.sort()
        tmp_str = ''.join(tmp_list)
        if signature == hashlib.sha1(tmp_str.encode('utf-8')).hexdigest():
            return True
        else:
            return False

    def generate_jsapi_signature(self, timestamp, noncestr, url, jsapi_ticket=None):
        """
        使用 jsapi_ticket 对 url 进行签名
        :param timestamp: 时间戳
        :param noncestr: 随机数
        :param url: 要签名的 url，不包含 # 及其后面部分
        :param jsapi_ticket: (可选参数) jsapi_ticket 值 (如不提供将自动通过 appid 和 appsecret 获取)
        :return: 返回sha1签名的hexdigest值
        """
        if not jsapi_ticket:
            jsapi_ticket = self.jsapi_ticket
        data = {
            'jsapi_ticket': jsapi_ticket,
            'noncestr': noncestr,
            'timestamp': timestamp,
            'url': url,
        }
        keys = data.keys()
        keys.sort()
        data_str = '&'.join(['%s=%s' % (key, data[key]) for key in keys])
        signature = hashlib.sha1(data_str.encode('utf-8')).hexdigest()
        return signature

    def parse_data(self, data):
        """
        解析微信服务器发送过来的数据并保存类中
        :param data: HTTP Request 的 Body 数据
        :raises ParseError: 解析微信服务器数据错误, 数据不合法
        """
        result = {}
        if type(data) == unicode:
            data = data.encode('utf-8')
        elif type(data) == str:
            pass
        else:
            raise ParseError()

        try:
            xml = XMLStore(xmlstring=data)
        except Exception:
            raise ParseError()

        result = xml.xml2dict
        result['raw'] = data
        result['type'] = result.pop('MsgType').lower()

        message_type = MESSAGE_TYPES.get(result['type'], UnknownMessage)
        self.__message = message_type(result)
        self.__is_parse = True

    @property
    def message(self):
        return self.get_message()

    def get_message(self):
        """
        获取解析好的 WechatMessage 对象
        :return: 解析好的 WechatMessage 对象
        """
        self._check_parse()

        return self.__message

    def get_access_token(self):
        """
        获取 Access Token 及 Access Token 过期日期, 仅供缓存使用, 如果希望得到原生的 Access Token 请求数据请使用 :func:`grant_token`
        :return: dict 对象, key 包括 `access_token` 及 `access_token_expires_at`
        """
        self._check_appid_appsecret()

        return {
            'access_token': self.access_token,
            'access_token_expires_at': self.__access_token_expires_at,
        }

    def get_jsapi_ticket(self):
        """
        获取 Jsapi Ticket 及 Jsapi Ticket 过期日期, 仅供缓存使用, 如果希望得到原生的 Jsapi Ticket 请求数据请使用 :func:`grant_jsapi_ticket`
        :return: dict 对象, key 包括 `jsapi_ticket` 及 `jsapi_ticket_expires_at`
        """
        self._check_appid_appsecret()

        return {
            'jsapi_ticket': self.jsapi_ticket,
            'jsapi_ticket_expires_at': self.__jsapi_ticket_expires_at,
        }

    def response_text(self, content, escape=False):
        """
        将文字信息 content 组装为符合微信服务器要求的响应数据
        :param content: 回复文字
        :param escape: 是否转义该文本内容 (默认不转义)
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()
        content = self._transcoding(content)
        if escape:
            content = cgi.escape(content)

        return TextReply(message=self.__message, content=content).render()

    def response_image(self, media_id):
        """
        将 media_id 所代表的图片组装为符合微信服务器要求的响应数据
        :param media_id: 图片的 MediaID
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()

        return ImageReply(message=self.__message, media_id=media_id).render()

    def response_voice(self, media_id):
        """
        将 media_id 所代表的语音组装为符合微信服务器要求的响应数据
        :param media_id: 语音的 MediaID
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()

        return VoiceReply(message=self.__message, media_id=media_id).render()

    def response_video(self, media_id, title=None, description=None):
        """
        将 media_id 所代表的视频组装为符合微信服务器要求的响应数据
        :param media_id: 视频的 MediaID
        :param title: 视频消息的标题
        :param description: 视频消息的描述
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()
        title = self._transcoding(title)
        description = self._transcoding(description)

        return VideoReply(message=self.__message, media_id=media_id, title=title, description=description).render()

    def response_music(self, music_url, title=None, description=None, hq_music_url=None, thumb_media_id=None):
        """
        将音乐信息组装为符合微信服务器要求的响应数据
        :param music_url: 音乐链接
        :param title: 音乐标题
        :param description: 音乐描述
        :param hq_music_url: 高质量音乐链接, WIFI环境优先使用该链接播放音乐
        :param thumb_media_id: 缩略图的 MediaID
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()
        music_url = self._transcoding(music_url)
        title = self._transcoding(title)
        description = self._transcoding(description)
        hq_music_url = self._transcoding(hq_music_url)

        return MusicReply(message=self.__message, title=title, description=description, music_url=music_url,
                          hq_music_url=hq_music_url, thumb_media_id=thumb_media_id).render()

    def response_news(self, articles):
        """
        将新闻信息组装为符合微信服务器要求的响应数据
        :param articles: list 对象, 每个元素为一个 dict 对象, key 包含 `title`, `description`, `picurl`, `url`
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()
        for article in articles:
            if article.get('title'):
                article['title'] = self._transcoding(article['title'])
            if article.get('description'):
                article['description'] = self._transcoding(article['description'])
            if article.get('picurl'):
                article['picurl'] = self._transcoding(article['picurl'])
            if article.get('url'):
                article['url'] = self._transcoding(article['url'])

        news = ArticleReply(message=self.__message)
        for article in articles:
            article = Article(**article)
            news.add_article(article)
        return news.render()

    def grant_token(self, override=True):
        """
        获取 Access Token
        详情请参考 http://mp.weixin.qq.com/wiki/11/0e4b294685f817b95cbed85ba5e82b8f.html
        :param override: 是否在获取的同时覆盖已有 access_token (默认为True)
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        response_json = self._get(
            url="https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self.__appid,
                "secret": self.__appsecret,
            }
        )

        if override:
            self.__access_token = response_json['access_token']
            self.__access_token_expires_at = int(time.time()) + response_json['expires_in']

            expires_in = int(response_json['expires_in'])
            self.__client.set('access_token', self.__access_token, expires_in)
            self.__client.set('access_token_expires_at', self.__access_token_expires_at, expires_in)

        return response_json

    def grant_jsapi_ticket(self, override=True):
        """
        获取 Jsapi Ticket
        详情请参考 http://mp.weixin.qq.com/wiki/7/aaa137b55fb2e0456bf8dd9148dd613f.html#.E9.99.84.E5.BD.951-JS-SDK.E4.BD.BF.E7.94.A8.E6.9D.83.E9.99.90.E7.AD.BE.E5.90.8D.E7.AE.97.E6.B3.95
        :param override: 是否在获取的同时覆盖已有 jsapi_ticket (默认为True)
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()
        # force to grant new access_token to avoid invalid credential issue
        self.grant_token()

        response_json = self._get(
            url="https://api.weixin.qq.com/cgi-bin/ticket/getticket",
            params={
                "access_token": self.access_token,
                "type": "jsapi",
            }
        )
        if override:
            self.__jsapi_ticket = response_json['ticket']
            self.__jsapi_ticket_expires_at = int(time.time()) + response_json['expires_in']
        return response_json

    def create_menu(self, menu_data):
        """
        创建自定义菜单 ::

            # -*- coding: utf-8 -*-
            wechat = WechatBasic(appid='appid', appsecret='appsecret')
            wechat.create_menu({
                'button':[
                    {
                        'type': 'click',
                        'name': '今日歌曲',
                        'key': 'V1001_TODAY_MUSIC'
                    },
                    {
                        'type': 'click',
                        'name': '歌手简介',
                        'key': 'V1001_TODAY_SINGER'
                    },
                    {
                        'name': '菜单',
                        'sub_button': [
                            {
                                'type': 'view',
                                'name': '搜索',
                                'url': 'http://www.soso.com/'
                            },
                            {
                                'type': 'view',
                                'name': '视频',
                                'url': 'http://v.qq.com/'
                            },
                            {
                                'type': 'click',
                                'name': '赞一下我们',
                                'key': 'V1001_GOOD'
                            }
                        ]
                    }
                ]})

        详情请参考 http://mp.weixin.qq.com/wiki/13/43de8269be54a0a6f64413e4dfa94f39.html
        :param menu_data: Python 字典
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        menu_data = self._transcoding_dict(menu_data)
        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/menu/create',
            data=menu_data
        )

    def get_menu(self):
        """
        查询自定义菜单
        详情请参考 http://mp.weixin.qq.com/wiki/16/ff9b7b85220e1396ffa16794a9d95adc.html
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._get('https://api.weixin.qq.com/cgi-bin/menu/get')

    def delete_menu(self):
        """
        删除自定义菜单
        详情请参考 http://mp.weixin.qq.com/wiki/16/8ed41ba931e4845844ad6d1eeb8060c8.html
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._get('https://api.weixin.qq.com/cgi-bin/menu/delete')

    def upload_media(self, media_type, media_file, extension=''):
        """
        上传多媒体文件
        详情请参考 http://mp.weixin.qq.com/wiki/10/78b15308b053286e2a66b33f0f0f5fb6.html
        :param media_type: 媒体文件类型，分别有图片（image）、语音（voice）、视频（video）和缩略图（thumb）
        :param media_file: 要上传的文件，一个 File object 或 StringIO object
        :param extension: 如果 media_file 传入的为 StringIO object，那么必须传入 extension 显示指明该媒体文件扩展名，如 ``mp3``, ``amr``；如果 media_file 传入的为 File object，那么该参数请留空
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()
        if not isinstance(media_file, file) and not isinstance(media_file, StringIO):
            raise ValueError('Parameter media_file must be file object or StringIO.StringIO object.')
        if isinstance(media_file, StringIO) and extension.lower() not in ['jpg', 'jpeg', 'amr', 'mp3', 'mp4']:
            raise ValueError('Please provide \'extension\' parameters when the type of \'media_file\' is \'StringIO.StringIO\'.')
        if isinstance(media_file, file):
            extension = media_file.name.split('.')[-1]
            if extension.lower() not in ['jpg', 'jpeg', 'amr', 'mp3', 'mp4']:
                raise ValueError('Invalid file type.')

        ext = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'amr': 'audio/amr',
            'mp3': 'audio/mpeg',
            'mp4': 'video/mp4',
        }
        if isinstance(media_file, StringIO):
            filename = 'temp.' + extension
        else:
            filename = media_file.name

        return self._post(
            url='http://file.api.weixin.qq.com/cgi-bin/media/upload',
            params={
                'access_token': self.access_token,
                'type': media_type,
            },
            files={
                'media': (filename, media_file, ext[extension])
            }
        )

    def download_media(self, media_id):
        """
        下载多媒体文件
        详情请参考 http://mp.weixin.qq.com/wiki/10/78b15308b053286e2a66b33f0f0f5fb6.html
        :param media_id: 媒体文件 ID
        :return: requests 的 Response 实例
        """
        self._check_appid_appsecret()

        return requests.get(
            'http://file.api.weixin.qq.com/cgi-bin/media/get',
            params={
                'access_token': self.access_token,
                'media_id': media_id,
            },
            stream=True,
        )

    def create_group(self, name):
        """
        创建分组
        详情请参考 http://mp.weixin.qq.com/wiki/13/be5272dc4930300ba561d927aead2569.html
        :param name: 分组名字（30个字符以内）
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/groups/create',
            data={
                'group': {
                    'name': name,
                },
            }
        )

    def get_groups(self):
        """
        查询所有分组
        详情请参考 http://mp.weixin.qq.com/wiki/13/be5272dc4930300ba561d927aead2569.html
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._get('https://api.weixin.qq.com/cgi-bin/groups/get')

    def get_group_by_id(self, openid):
        """
        查询用户所在分组
        详情请参考 http://mp.weixin.qq.com/wiki/13/be5272dc4930300ba561d927aead2569.html
        :param openid: 用户的OpenID
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/groups/getid',
            data={
                'openid': openid,
            }
        )

    def update_group(self, group_id, name):
        """
        修改分组名
        详情请参考 http://mp.weixin.qq.com/wiki/13/be5272dc4930300ba561d927aead2569.html
        :param group_id: 分组id，由微信分配
        :param name: 分组名字（30个字符以内）
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/groups/update',
            data={
                'group': {
                    'id': int(group_id),
                    'name': name,
                }
            }
        )

    def move_user(self, user_id, group_id):
        """
        移动用户分组
        详情请参考 http://mp.weixin.qq.com/wiki/13/be5272dc4930300ba561d927aead2569.html
        :param user_id: 用户 ID 。 就是你收到的 WechatMessage 的 source
        :param group_id: 分组 ID
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/groups/members/update',
            data={
                'openid': user_id,
                'to_groupid': group_id,
            }
        )

    def get_user_info(self, user_id, lang='zh_CN'):
        """
        获取用户基本信息
        详情请参考 http://mp.weixin.qq.com/wiki/14/bb5031008f1494a59c6f71fa0f319c66.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param lang: 返回国家地区语言版本，zh_CN 简体，zh_TW 繁体，en 英语
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._get(
            url='https://api.weixin.qq.com/cgi-bin/user/info',
            params={
                'access_token': self.access_token,
                'openid': user_id,
                'lang': lang,
            }
        )

    def get_followers(self, first_user_id=None):
        """
        获取关注者列表
        详情请参考 http://mp.weixin.qq.com/wiki/3/17e6919a39c1c53555185907acf70093.html
        :param first_user_id: 可选。第一个拉取的OPENID，不填默认从头开始拉取
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        params = {
            'access_token': self.access_token,
        }
        if first_user_id:
            params['next_openid'] = first_user_id
        return self._get('https://api.weixin.qq.com/cgi-bin/user/get', params=params)

    def send_text_message(self, user_id, content):
        """
        发送文本消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param content: 消息正文
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'text',
                'text': {
                    'content': content,
                },
            }
        )

    def send_image_message(self, user_id, media_id):
        """
        发送图片消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param media_id: 图片的媒体ID。 可以通过 :func:`upload_media` 上传。
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'image',
                'image': {
                    'media_id': media_id,
                },
            }
        )

    def send_voice_message(self, user_id, media_id):
        """
        发送语音消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param media_id: 发送的语音的媒体ID。 可以通过 :func:`upload_media` 上传。
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'voice',
                'voice': {
                    'media_id': media_id,
                },
            }
        )

    def send_video_message(self, user_id, media_id, title=None, description=None):
        """
        发送视频消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param media_id: 发送的视频的媒体ID。 可以通过 :func:`upload_media` 上传。
        :param title: 视频消息的标题
        :param description: 视频消息的描述
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        video_data = {
            'media_id': media_id,
        }
        if title:
            video_data['title'] = title
        if description:
            video_data['description'] = description

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'video',
                'video': video_data,
            }
        )

    def send_music_message(self, user_id, url, hq_url, thumb_media_id, title=None, description=None):
        """
        发送音乐消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param url: 音乐链接
        :param hq_url: 高品质音乐链接，wifi环境优先使用该链接播放音乐
        :param thumb_media_id: 缩略图的媒体ID。 可以通过 :func:`upload_media` 上传。
        :param title: 音乐标题
        :param description: 音乐描述
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        music_data = {
            'musicurl': url,
            'hqmusicurl': hq_url,
            'thumb_media_id': thumb_media_id,
        }
        if title:
            music_data['title'] = title
        if description:
            music_data['description'] = description

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'music',
                'music': music_data,
            }
        )

    def send_article_message(self, user_id, articles):
        """
        发送图文消息
        详情请参考 http://mp.weixin.qq.com/wiki/7/12a5a320ae96fecdf0e15cb06123de9f.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source
        :param articles: list 对象, 每个元素为一个 dict 对象, key 包含 `title`, `description`, `picurl`, `url`
        :return: 返回的 JSON 数据包
        """
        self._check_appid_appsecret()

        articles_data = []
        for article in articles:
            article = Article(**article)
            articles_data.append({
                'title': article.title,
                'description': article.description,
                'url': article.url,
                'picurl': article.picurl,
            })
        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/custom/send',
            data={
                'touser': user_id,
                'msgtype': 'news',
                'news': {
                    'articles': articles_data,
                },
            }
        )

    def create_qrcode(self, data):
        """
        创建二维码
        详情请参考 http://mp.weixin.qq.com/wiki/18/28fc21e7ed87bec960651f0ce873ef8a.html
        :param data: 你要发送的参数 dict
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_appid_appsecret()

        data = self._transcoding_dict(data)
        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/qrcode/create',
            data=data
        )

    def show_qrcode(self, ticket):
        """
        通过ticket换取二维码
        详情请参考 http://mp.weixin.qq.com/wiki/18/28fc21e7ed87bec960651f0ce873ef8a.html
        :param ticket: 二维码 ticket 。可以通过 :func:`create_qrcode` 获取到
        :return: 返回的 Request 对象
        """
        self._check_appid_appsecret()

        return requests.get(
            url='https://mp.weixin.qq.com/cgi-bin/showqrcode',
            params={
                'ticket': ticket
            }
        )

    def set_template_industry(self, industry_id1, industry_id2):
        """
        设置所属行业
        详情请参考 http://mp.weixin.qq.com/wiki/17/304c1885ea66dbedf7dc170d84999a9d.html
        :param industry_id1: 主营行业代码
        :param industry_id2: 副营行业代码
        :return: 返回的 JSON 数据包
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/template/api_set_industry',
            data={
                'industry_id1': str(industry_id1),
                'industry_id2': str(industry_id2),
            }
        )

    def get_template_id(self, template_id_short):
        """
        获得模板ID
        详情请参考 http://mp.weixin.qq.com/wiki/17/304c1885ea66dbedf7dc170d84999a9d.html
        :param template_id_short: 模板库中模板的编号，有“TM**”和“OPENTMTM**”等形式
        :return: 返回的 JSON 数据包
        """
        self._check_appid_appsecret()

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/template/api_add_template',
            data={
                'template_id_short': str(template_id_short),
            }
        )

    def send_template_message(self, user_id, template_id, data, url='', topcolor='#FF0000'):
        """
        发送模版消息
        详情请参考 http://mp.weixin.qq.com/wiki/17/304c1885ea66dbedf7dc170d84999a9d.html
        :param user_id: 用户 ID, 就是你收到的 WechatMessage 的 source (OpenID)
        :param template_id: 模板ID
        :param data: 模板消息数据 (dict形式)，示例如下：
        {
            "first": {
               "value": "恭喜你购买成功！",
               "color": "#173177"
            },
            "keynote1":{
               "value": "巧克力",
               "color": "#173177"
            },
            "keynote2": {
               "value": "39.8元",
               "color": "#173177"
            },
            "keynote3": {
               "value": "2014年9月16日",
               "color": "#173177"
            },
            "remark":{
               "value": "欢迎再次购买！",
               "color": "#173177"
            }
        }
        :param url: 跳转地址 (默认为空)
        :param topcolor: 顶部颜色RGB值 (默认 '#FF0000' )
        :return: 返回的 JSON 数据包
        """
        self._check_appid_appsecret()

        unicode_data = {}
        if data:
            unicode_data = self._transcoding_dict(data)

        return self._post(
            url='https://api.weixin.qq.com/cgi-bin/message/template/send',
            data={
                'touser': user_id,
                "template_id": template_id,
                "url": url,
                "topcolor": topcolor,
                "data": unicode_data
            }
        )

    @property
    def access_token(self):
        self._check_appid_appsecret()

        self.__access_token = self.__client.get('access_token')
        self.__access_token_expires_at = self.__client.get('access_token_expires_at')

        if self.__access_token and self.__access_token_expires_at:
            now = time.time()
            if self.__access_token_expires_at - now > 60:
                return self.__access_token

        self.grant_token()
        return self.__access_token

    @property
    def jsapi_ticket(self):
        self._check_appid_appsecret()

        if self.__jsapi_ticket:
            now = time.time()
            if self.__jsapi_ticket_expires_at - now > 60:
                return self.__jsapi_ticket
        self.grant_jsapi_ticket()
        return self.__jsapi_ticket

    def _check_token(self):
        """
        检查 Token 是否存在
        :raises NeedParamError: Token 参数没有在初始化的时候提供
        """
        if not self.__token:
            raise NeedParamError('Please provide Token parameter in the construction of class.')

    def _check_appid_appsecret(self):
        """
        检查 AppID 和 AppSecret 是否存在
        :raises NeedParamError: AppID 或 AppSecret 参数没有在初始化的时候完整提供
        """
        if not self.__appid or not self.__appsecret:
            raise NeedParamError('Please provide app_id and app_secret parameters in the construction of class.')

    def _check_parse(self):
        """
        检查是否成功解析微信服务器传来的数据
        :raises NeedParseError: 需要解析微信服务器传来的数据
        """
        if not self.__is_parse:
            raise NeedParseError()

    def _check_official_error(self, json_data):
        """
        检测微信公众平台返回值中是否包含错误的返回码
        :raises OfficialAPIError: 如果返回码提示有错误，抛出异常；否则返回 True
        """
        if "errcode" in json_data and json_data["errcode"] != 0:
            raise OfficialAPIError("{}: {}".format(json_data["errcode"], json_data["errmsg"]))

    def _request(self, method, url, **kwargs):
        """
        向微信服务器发送请求
        :param method: 请求方法
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        if "params" not in kwargs:
            kwargs["params"] = {
                "access_token": self.access_token,
            }
        if isinstance(kwargs.get("data", ""), dict):
            body = json.dumps(kwargs["data"], ensure_ascii=False)
            body = body.encode('utf8')
            kwargs["data"] = body

        r = requests.request(
            method=method,
            url=url,
            **kwargs
        )
        r.raise_for_status()
        response_json = r.json()
        self._check_official_error(response_json)
        return response_json

    def _get(self, url, **kwargs):
        """
        使用 GET 方法向微信服务器发出请求
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        return self._request(
            method="get",
            url=url,
            **kwargs
        )

    def _post(self, url, **kwargs):
        """
        使用 POST 方法向微信服务器发出请求
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        return self._request(
            method="post",
            url=url,
            **kwargs
        )

    def _transcoding(self, data):
        """
        编码转换
        :param data: 需要转换的数据
        :return: 转换好的数据
        """
        if not data:
            return data

        result = None
        if isinstance(data, str):
            result = data.decode('utf-8')
        else:
            result = data
        return result

    def _transcoding_list(self, data):
        """
        编码转换 for list
        :param data: 需要转换的 list 数据
        :return: 转换好的 list
        """
        if not isinstance(data, list):
            raise ValueError('Parameter data must be list object.')

        result = []
        for item in data:
            if isinstance(item, dict):
                result.append(self._transcoding_dict(item))
            elif isinstance(item, list):
                result.append(self._transcoding_list(item))
            else:
                result.append(item)
        return result

    def _transcoding_dict(self, data):
        """
        编码转换 for dict
        :param data: 需要转换的 dict 数据
        :return: 转换好的 dict
        """
        if not isinstance(data, dict):
            raise ValueError('Parameter data must be dict object.')

        result = {}
        for k, v in data.items():
            k = self._transcoding(k)
            if isinstance(v, dict):
                v = self._transcoding_dict(v)
            elif isinstance(v, list):
                v = self._transcoding_list(v)
            else:
                v = self._transcoding(v)
            result.update({k: v})

        return result

    def _check_mch_id(self):
        """
        检查商户号是否存在
        :raises NeedParamError: mch_id参数没有在初始化的时候提供
        """
        if not self.__mch_id:
            raise NeedParamError("Please provide mch_id parameters in the construction of class.")

    def _check_api_key(self):
        """
        检查api_key是否存在
        :raises NeedParamError: api_key参数没有在初始化的时候提供
        """
        if not self.__api_key:
            raise NeedParamError("Please provide api_key parameters in the construction of class.")

    @staticmethod
    def _check_official_xml_error(json_data):
        if "err_code" in json_data:
            raise OfficialAPIError((u"{}: {}".format(json_data["err_code"], json_data["err_code_des"])).encode("utf-8"))

        return_code = json_data.get("return_code")
        if return_code.upper() != "SUCCESS":
            raise OfficialAPIError((u"{}: {}".format(json_data["return_code"], json_data["return_msg"])).encode("utf-8"))

    def _post_xml(self, url, data):
        r = requests.request(
            'POST',
            url,
            headers={'Content-Type': 'application/xml'},
            data=dict2xml(data)
        )

        r.raise_for_status()

        json_data = xml2dict(r.content)
        self._check_official_xml_error(json_data)

        return json_data

    def generate_sign(self, _params):
        """
        获取请求参数签名. 微信官方解释: 在API调用时用来按照指定规则对您的请求参数进行签名，
        服务器收到您的请求时会进行签名验证，既可以界定您的身份也可以防止其他人恶意篡改请求数据。
        部分API单独使用API密钥签名进行安全加固，部分安全性要求更高的API会要求使用API密
        钥签名和API证书同时进行安全加固
        :param params 参数字典
        :return 参数签名
        """
        self._check_api_key()

        params = dict(_params)

        # 去除空值字段
        [(not _params.get(key)) and params.pop(key) for key in _params]

        # 参数转URL键值对的格式字符串
        sorted_keys = sorted(params.keys())
        kv_list = []

        for key in sorted_keys:
            value = params.get(key)

            if isinstance(value, (int, float, bool)):
                value = str(value)

            if type(value) == unicode:
                value = value.encode('utf-8')
            elif type(value) == str:
                value = value.decode('utf-8').encode('utf-8')
            else:
                raise ValueError("not support type: %s" % type(value))

            kv_list.append("=".join([key, value]))

        # 拼接API_KEY
        kv_list.append("key=%s" % self.__api_key)

        # 取MD5、大写化
        return hashlib.md5("&".join(kv_list)).hexdigest().upper()

    @staticmethod
    def generate_nonce_str():
        return "".join(random.sample(string.digits + string.letters, 32))

    def web_authorize_url(self, redirect_uri, scope="snsapi_base"):
        """
        如果用户在微信客户端中访问第三方网页，公众号可以通过微信网页授权机制，来获取用户基本信息，进而实现业务逻辑
        详细说明：http://mp.weixin.qq.com/wiki/17/c0f37d5704f0b64713d5d2c37b468d75.html
        :param redirect_uri: 授权后的跳转地址。以snsapi_base为scope发起的网页授权，
                             是用来获取进入页面的用户的openid的，并且是静默授权并自动
                             跳转到回调页的。用户感知的就是直接进入了回调页（往往是业务页面）
        :param scope: 现在只使用snsapi_base
        :return: 微信授权页的url
        """
        request = requests.Request(
            method='GET',
            url="https://open.weixin.qq.com/connect/oauth2/authorize#wechat_redirect",
            params={
                "appid": self.__appid,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scope,
                "state": 0
            }
        )

        p = request.prepare()
        return p.url

    def web_authorize_access_token(self, code):
        """
        :param code: 通过微信网页授权得到的code, 根据此code可以获取access_token
        :return: access_token,
                 格式如下所示:
                 {
                   "access_token":"ACCESS_TOKEN",
                   "expires_in":7200,
                   "refresh_token":"REFRESH_TOKEN",
                   "openid":"OPENID",
                   "scope":"SCOPE",
                   "unionid": "o6_bmasdasdsad6_2sgVt7hMZOPfL"
                 }
        """
        return self._get(
            url="https://api.weixin.qq.com/sns/oauth2/access_token",
            params={
                "appid": self.__appid,
                "secret": self.__appsecret,
                "code": code,
                "grant_type": "authorization_code"
            }
        )

    def unified_order(self, body, out_trade_no, total_fee, spbill_create_ip,
                      notify_url, trade_type, detail=None, attach=None, fee_type=None,
                      time_start=None, time_expire=None, goods_tag=None,
                      product_id=None, openid=None):
        """
        :param body: 商品或支付单简要描述. String(32)
        :param out_trade_no: 商户系统内部的订单号,32个字符内、可包含字母. String(32)
        :param total_fee: 订单总金额，只能为整数. Int
        :param spbill_create_ip:  APP和网页支付提交用户端ip，Native支付填调用微信支付API的机器IP. String(16)
        :param notify_url: 接收微信支付异步通知回调地址. String=256
        :param trade_type: 取值如下：JSAPI，NATIVE，APP，WAP. String(16)

        # 可选参数
        :param detail: 商品名称明细列表. String(8192)
        :param attach: 附加数据，在查询API和支付通知中原样返回，该字段主要用于商户携带订单的自定义数据. String(127)
        :param fee_type: 符合ISO 4217标准的三位字母代码，默认人民币：CNY
        :param time_start: 订单生成时间，格式为yyyyMMddHHmmss，如2009年12月25日9点10分10秒表示为20091225091010
        :param time_expire: 订单失效时间，格式为yyyyMMddHHmmss，如2009年12月27日9点10分10秒表示为20091227091010. 注意：最短失效时间间隔必须大于5分钟
        :param goods_tag: 商品标记，代金券或立减优惠功能的参数. String(32)
        :param product_id: rade_type=NATIVE，此参数必传。此id为二维码中包含的商品ID，商户自行定义. trade_type=NATIVE，此参数必传。此id为二维码中包含的商品ID，商户自行定义。
        :param open_id: trade_type=JSAPI，此参数必传，用户在商户appid下的唯一标识。下单前需要调用. String(128)

        参数及返回具体详情见官网文档 https://pay.weixin.qq.com/wiki/doc/api/jsapi.php?chapter=9_1

        :return: 微信api返回值
        """
        self._check_appid_appsecret()

        _params = locals()
        params = dict(_params)

        params.pop("self")
        [(not _params.get(key)) and params.pop(key) for key in _params]
        params.update({
            "appid": self.__appid,
            "mch_id": self.__mch_id,
            "nonce_str": self.generate_nonce_str(),
        })

        # 添加签名
        params["sign"] = self.generate_sign(params)

        return self._post_xml(
            'https://api.mch.weixin.qq.com/pay/unifiedorder',
            params
        )

    def order_query(self, transaction_id='', out_trade_no=''):
        """
        :param transaction_id: 微信的订单号，优先使用, String(32)
        :param out_trade_no: 商户系统内部的订单号，当没提供transaction_id时需要传这个。 1217752501201407033233368018

        参数及返回具体详情见官网文档 https://pay.weixin.qq.com/wiki/doc/api/native.php?chapter=9_2
        :return: 微信api返回值
        """
        if not transaction_id and not out_trade_no:
            raise NeedParamError('transaction_id and out_trade_no at least be specified one')

        params = {
            "appid": self.__appid,
            "mch_id": self.__mch_id,
            "transaction_id": transaction_id,
            "out_trade_no": out_trade_no,
            "nonce_str": self.generate_nonce_str(),
        }

        params["sign"] = self.generate_sign(params)

        return self._post_xml(
            'https://api.mch.weixin.qq.com/pay/orderquery',
            params
        )

    def check_weixin_pay_notify_data(self, data):
        self._check_official_xml_error(data)

    def generate_jsapi_pay_params(self, prepay_id):
        params = {
            "appId": self.__appid,
            "timeStamp": str(int(time.time())),
            "nonceStr": self.generate_nonce_str(),
            "package": "prepay_id=%s" % prepay_id,
            "signType": "MD5",
        }

        params["paySign"] = self.generate_sign(params)

        return params
