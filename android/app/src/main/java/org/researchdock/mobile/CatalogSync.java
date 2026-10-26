package org.researchdock.mobile;
import org.json.*;
import java.io.IOException;
import java.util.*;
/** Collects a fixed metadata snapshot/delta before the caller atomically writes any cache. */
final class CatalogSync {
 interface Fetcher { JSONObject get(String path)throws Exception; }
 static final class Result {final JSONArray documents;final long cursor;final boolean snapshot;Result(JSONArray d,long c,boolean s){documents=d;cursor=c;snapshot=s;}}
 static Result fetch(Fetcher api,JSONArray base,long cursor,boolean delta)throws Exception{
  try{return collect(api,base,cursor,delta);}catch(MobileApi.Failure error){if(error.status==409&&delta)return collect(api,new JSONArray(),0,false);throw error;}
 }
 private static Result collect(Fetcher api,JSONArray base,long cursor,boolean delta)throws Exception{
  Map<String,JSONObject> records=new HashMap<>();if(delta)for(int i=0;i<base.length();i++){JSONObject d=base.getJSONObject(i);records.put(d.getString("document_id"),d);}
  long until=-1,after=delta?cursor:0;String afterId="";int rounds=0;
  while(true){if(++rounds>1000)throw new IOException("同步变更过多，请稍后重试");String path="/v1/catalog?limit=100&mode="+(delta?"delta&after="+after:"snapshot&after_id="+afterId)+(until>=0?"&until="+until:"");JSONObject page=api.get(path);long high=page.getLong("cursor");if(high<0||until>=0&&high!=until)throw new IOException("目录快照发生变化，保留旧进度");until=high;JSONArray events=page.getJSONArray("events");
   for(int i=0;i<events.length();i++){JSONObject e=events.getJSONObject(i);String id=e.getString("document_id");long sequence=e.getLong("sequence");if(!id.matches("doc_[0-9A-Z]{26}")||sequence<1||sequence>until||delta&&sequence<=after||!delta&&id.compareTo(afterId)<=0)throw new IOException("目录分页无效，保留旧进度");if(delta)after=sequence;else afterId=id;
    if(e.getBoolean("deleted"))records.remove(id);else{JSONObject d=e.getJSONObject("document");if(!id.equals(d.getString("document_id"))||d.getInt("revision")<1||d.has("body"))throw new IOException("目录记录无效");records.put(id,d);}}
   boolean more=page.getBoolean("has_more");if(!more)break;if(events.length()==0)throw new IOException("目录分页没有前进，保留旧进度");
  }
  ArrayList<JSONObject> values=new ArrayList<>(records.values());values.sort((a,b)->{int result=b.optString("published_at").compareTo(a.optString("published_at"));return result!=0?result:a.optString("document_id").compareTo(b.optString("document_id"));});JSONArray documents=new JSONArray();for(JSONObject d:values)documents.put(d);return new Result(documents,until,!delta);
 }
}
