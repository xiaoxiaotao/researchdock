package org.researchdock.mobile;
import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import org.json.JSONObject;
import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;

/** Uses the reader's existing encrypted credential. No model secret is stored on the phone. */
final class MobileApi {
 private final SharedPreferences prefs;private final String connection;
 MobileApi(Context c){prefs=c.getSharedPreferences("reader",Context.MODE_PRIVATE);connection=connectionValue();}
 private String connectionValue(){java.util.Map<String,?> values=prefs.getAll();return String.valueOf(values.get("server"))+"\n"+String.valueOf(values.get("credential"));}
 boolean sameConnection(){return connection.equals(connectionValue());}
 boolean configured(){return !prefs.getString("server","").isEmpty()&&!prefs.getString("credential","").isEmpty();}
 private String token(String encrypted)throws Exception{String[] parts=encrypted.split(":");if(parts.length!=2)throw new IOException("请先在阅读器设置连接服务");KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,(SecretKey)ks.getKey("reader-token",null),new GCMParameterSpec(128,Base64.decode(parts[0],Base64.NO_WRAP)));return new String(cipher.doFinal(Base64.decode(parts[1],Base64.NO_WRAP)),StandardCharsets.UTF_8);}
 JSONObject request(String method,String path,JSONObject body)throws Exception{
  if(!sameConnection())throw new IOException("阅读连接已变更，请重新打开调研页");java.util.Map<String,?> config=prefs.getAll();URL url=new URL(String.valueOf(config.get("server"))+path);if(!"https".equals(url.getProtocol()))throw new IOException("请配置 HTTPS 阅读服务");
  HttpsURLConnection c=(HttpsURLConnection)url.openConnection();c.setInstanceFollowRedirects(false);c.setConnectTimeout(12000);c.setReadTimeout(20000);c.setRequestMethod(method);
  try{c.setRequestProperty("Authorization","Bearer "+token(String.valueOf(config.get("credential"))));if(body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=utf-8");try(OutputStream o=c.getOutputStream()){o.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
   int status=c.getResponseCode();InputStream stream=status==200?c.getInputStream():c.getErrorStream();ByteArrayOutputStream out=new ByteArrayOutputStream();
   if(stream!=null)try(InputStream in=stream){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>2_000_000)throw new IOException("服务响应过大");out.write(b,0,n);}}
   JSONObject result;try{result=new JSONObject(out.toString("UTF-8"));}catch(Exception e){throw new IOException("服务暂不可用，请稍后刷新");}
   if(status!=200){String message=result.optString("detail","");if(!message.isEmpty()&&message.length()<320&&!message.startsWith("["))throw new IOException(message);throw new IOException(status==401?"阅读凭据已失效，请重新配置":status==404?"服务尚未升级 AI 调研接口":"请求未完成，请稍后重试");}if(!sameConnection())throw new IOException("阅读连接已变更，请重新打开调研页");return result;
  }finally{c.disconnect();}
 }
}
